import uuid

from django.conf import settings
from django.contrib.auth.models import User as UserType
from django.db import models, transaction
from django.db.models.functions import Lower

from common.labeled_enum import LabeledEnumField
from common.models import TimestampedModel

from .enums import OrganizationInvitationStatus, OrganizationRole
from .exceptions import (
    InvitationRecipientMismatchError,
    InvitationStateError,
    LastActiveOwnerError,
)
from .managers import (
    OrganizationInvitationManager,
    OrganizationManager,
    OrganizationMemberManager,
)


class Organization( TimestampedModel ):
    """A tenancy boundary: the unit that owns domain objects.

    Users gain access only indirectly, through an OrganizationMember. An
    organization may sit in a hierarchy via `parent`; the hierarchy is purely
    structural in this version (no behavioural inheritance).
    """

    objects = OrganizationManager()

    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    name = models.CharField(
        'Name',
        max_length = 64,
        null = False,
        blank = False,
    )
    parent = models.ForeignKey(
        'self',
        verbose_name = 'Parent',
        related_name = 'children',
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
    )

    class Meta:
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'

    def __str__(self):
        return self.name


class OrganizationMember( TimestampedModel ):
    """A user's membership in an organization, carrying their role.

    The model guards one invariant: an organization must always retain at least
    one active owner. An operation that would drop the last active owner --
    deleting, demoting, or deactivating it -- raises LastActiveOwnerError. The
    check takes a row lock on the organization (via select_for_update) to
    serialize concurrent owner changes on backends that support it; SQLite,
    which ignores select_for_update, serializes writers with its database-level
    write lock instead. (Bulk queryset operations such as
    `QuerySet.update()`/`delete()` bypass these hooks and are not guarded.)
    """

    _LAST_OWNER_MESSAGE = 'An organization must always retain at least one active owner.'

    objects = OrganizationMemberManager()

    organization = models.ForeignKey(
        Organization,
        verbose_name = 'Organization',
        related_name = 'members',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name = 'User',
        related_name = 'organization_members',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    organization_role = LabeledEnumField(
        OrganizationRole,
        verbose_name = 'Role',
    )
    is_active = models.BooleanField(
        'Is Active',
        default = True,
    )

    class Meta:
        verbose_name = 'Organization Member'
        verbose_name_plural = 'Organization Members'
        constraints = [
            models.UniqueConstraint(
                fields = [ 'organization', 'user' ],
                name = 'unique_organization_member',
            ),
        ]

    def __str__(self):
        return f'{self.user} @ {self.organization} ({self.organization_role.label})'

    @property
    def is_active_owner(self) -> bool:
        return bool( self.is_active and ( self.organization_role == OrganizationRole.OWNER ) )

    def save( self, *args, **kwargs ):
        # Only an update that strips active-owner status from a current active
        # owner can threaten the invariant; everything else saves directly.
        if self.pk is not None:
            previous = self.__class__.objects.filter( pk = self.pk ).first()
            if (    ( previous is not None )
                    and ( previous.is_active_owner )
                    and ( not self.is_active_owner ) ):
                with transaction.atomic():
                    self._assert_another_active_owner_exists()
                    return super().save( *args, **kwargs )
        return super().save( *args, **kwargs )

    def delete( self, *args, **kwargs ):
        if self.is_active_owner:
            with transaction.atomic():
                self._assert_another_active_owner_exists()
                return super().delete( *args, **kwargs )
        return super().delete( *args, **kwargs )

    def deactivate( self ):
        """Soft-leave: mark the membership inactive, retaining the row.

        This is the conventional "left the organization" path (a person keeps
        their single membership row and can be reactivated on a later accept).
        It goes through `save()`, so deactivating the last active owner is
        rejected.
        """
        self.is_active = False
        self.save()
        return

    def _assert_another_active_owner_exists( self ):
        # Lock the organization row so concurrent owner changes serialize: two
        # simultaneous demotions cannot each observe the other as still active.
        # (select_for_update is a no-op on SQLite, which relies on its global
        # write lock instead.)
        Organization.objects.select_for_update().get( pk = self.organization_id )
        another_exists = self.__class__.objects.active_owners(
            self.organization_id
        ).exclude( pk = self.pk ).exists()
        if not another_exists:
            raise LastActiveOwnerError( self._LAST_OWNER_MESSAGE )
        return


class OrganizationInvitation( TimestampedModel ):
    """An invitation to join an organization in a role.

    The invitation is the durable record of a pending or closed invite. The role
    to grant lives here; no membership exists until acceptance. The invitee is
    identified by an email address, by a directly referenced user (e.g. resolved
    from a UUID), or both -- at least one is required (enforced by a check
    constraint). Accepting creates or reactivates the active membership.

    At most one WAITING invitation may exist per organization for a given email,
    and per organization for a given user; closed invitations are retained as
    history and do not block re-inviting.
    """

    objects = OrganizationInvitationManager()

    organization = models.ForeignKey(
        Organization,
        verbose_name = 'Organization',
        related_name = 'invitations',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name = 'Invited By',
        related_name = 'sent_organization_invitations',
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
    )
    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name = 'Invited User',
        related_name = 'received_organization_invitations',
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
    )
    email_address = models.EmailField(
        'Email Address',
        null = True,
        blank = True,
    )
    organization_role = LabeledEnumField(
        OrganizationRole,
        verbose_name = 'Role',
    )
    status = LabeledEnumField(
        OrganizationInvitationStatus,
        verbose_name = 'Status',
    )

    class Meta:
        verbose_name = 'Organization Invitation'
        verbose_name_plural = 'Organization Invitations'
        constraints = [
            models.CheckConstraint(
                condition = (
                    models.Q( email_address__isnull = False )
                    | models.Q( invited_user__isnull = False )
                ),
                name = 'invitation_has_email_or_user',
            ),
            models.UniqueConstraint(
                Lower( 'email_address' ),
                'organization',
                condition = models.Q(
                    status = str( OrganizationInvitationStatus.WAITING ),
                    email_address__isnull = False,
                ),
                name = 'unique_pending_invitation_per_org_email',
            ),
            models.UniqueConstraint(
                'invited_user',
                'organization',
                condition = models.Q(
                    status = str( OrganizationInvitationStatus.WAITING ),
                    invited_user__isnull = False,
                ),
                name = 'unique_pending_invitation_per_org_user',
            ),
        ]

    def __str__(self):
        recipient = self.email_address or self.invited_user
        return f'{recipient} -> {self.organization} ({self.status.label})'

    def accept( self, user : UserType ) -> OrganizationMember:
        """Accept this invitation on behalf of `user`, returning the active
        OrganizationMember.

        Requires WAITING status and that `user` is the invitation's recipient --
        either the linked `invited_user`, or a case-insensitive match on the
        invitation email. Idempotent if the user already has a membership: an
        inactive one is reactivated, and an existing role is left unchanged.
        """
        if self.status != OrganizationInvitationStatus.WAITING:
            raise InvitationStateError( 'Only a pending invitation can be accepted.' )
        if not self._can_be_accepted_by( user ):
            raise InvitationRecipientMismatchError(
                'The accepting user does not match the invitation.'
            )
        with transaction.atomic():
            member, created = OrganizationMember.objects.get_or_create(
                organization = self.organization,
                user = user,
                defaults = {
                    'organization_role': self.organization_role,
                    'is_active': True,
                },
            )
            if not created and not member.is_active:
                member.is_active = True
                member.save()
            self.invited_user = user
            self.status = OrganizationInvitationStatus.ACCEPTED
            self.save()
        return member

    def decline( self ):
        """Decline this pending invitation (by the invitee)."""
        self._close( OrganizationInvitationStatus.DECLINED )
        return

    def revoke( self ):
        """Revoke this pending invitation (by the organization)."""
        self._close( OrganizationInvitationStatus.REVOKED )
        return

    def _close( self, new_status : OrganizationInvitationStatus ):
        if self.status != OrganizationInvitationStatus.WAITING:
            raise InvitationStateError( 'Only a pending invitation can change state.' )
        self.status = new_status
        self.save()
        return

    def _can_be_accepted_by( self, user : UserType ) -> bool:
        identity_matches = bool(
            ( self.invited_user_id is not None )
            and ( self.invited_user_id == user.pk )
        )
        if identity_matches:
            return True
        email_matches = bool(
            ( self.email_address )
            and ( user.email )
            and ( user.email.lower() == self.email_address.lower() )
        )
        return email_matches
