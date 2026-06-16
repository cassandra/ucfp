from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User as UserType
from django.db import models, transaction

from .enums import OrganizationInvitationStatus, OrganizationRole
from .exceptions import AlreadyActiveMemberError, DuplicateInvitationError

if TYPE_CHECKING:
    # Imported only for type annotations; a runtime import would create a
    # managers <-> models cycle (models imports the managers below).
    from .models import Organization, OrganizationInvitation


class OrganizationManager( models.Manager ):

    @transaction.atomic
    def create_for_owner( self,
                          user : UserType,
                          name : str       ) -> 'Organization':
        """Create an organization named `name`, owned by `user` as an active
        OWNER.

        Self-contained: the organization and its owner membership are created in
        one transaction, so a partial failure can never leave an ownerless
        organization.
        """
        organization = self.create( name = name )
        organization.members.create(
            user = user,
            organization_role = OrganizationRole.OWNER,
        )
        return organization

    @transaction.atomic
    def create_for_email( self, email : str, name : str ) -> 'Organization':
        """Create a passwordless user for `email` and an organization named
        `name` that they own.

        The user authenticates via magic link (no usable password). The whole
        operation is atomic.
        """
        user = get_user_model().objects.create_user( email = email )
        return self.create_for_owner( user, name )


class OrganizationMemberManager( models.Manager ):

    def for_user( self, user : UserType ) -> models.QuerySet:
        """Active memberships for `user` (the organizations they can access)."""
        return self.filter( user = user, is_active = True )

    def active_owners( self, organization : 'Organization' ) -> models.QuerySet:
        """Active OWNER memberships of `organization`."""
        return self.filter(
            organization = organization,
            organization_role = OrganizationRole.OWNER,
            is_active = True,
        )


class OrganizationInvitationManager( models.Manager ):

    def invite( self,
                organization : 'Organization',
                role         : OrganizationRole,
                invited_by   : UserType,
                email        : str      = None,
                invited_user : UserType = None ) -> 'OrganizationInvitation':
        """Create a WAITING invitation to join `organization` as `role`, sent by
        `invited_by` (required).

        The invitee is identified by `email`, by `invited_user` (e.g. resolved
        from a UUID), or both -- at least one is required. When only `email` is
        given and it maps to an existing user, that user is linked as
        `invited_user` so deduplication is consistent across both dimensions.

        Raises:
          - ValueError if `invited_by` is None, or neither `email` nor
            `invited_user` is given;
          - AlreadyActiveMemberError if the resolved user is already an active
            member of the organization;
          - DuplicateInvitationError if a pending invitation already exists for
            this organization and the same email or user.

        Closed invitations (accepted/declined/revoked) are retained as history
        and do not block re-inviting; a former (inactive) member is re-invitable
        and is reactivated on acceptance.
        """
        if invited_by is None:
            raise ValueError( 'invited_by is required to create an invitation.' )
        if email is not None:
            email = email.strip() or None
        if ( email is None ) and ( invited_user is None ):
            raise ValueError( 'an invitation requires an email address or a user.' )
        if ( invited_user is None ) and ( email is not None ):
            invited_user = get_user_model().objects.filter( email__iexact = email ).first()
        if invited_user is not None:
            is_active_member = bool(
                invited_user.organization_members.filter(
                    organization = organization,
                    is_active = True,
                ).exists()
            )
            if is_active_member:
                raise AlreadyActiveMemberError(
                    'The invited user is already an active member of this organization.'
                )
        if self._pending_exists( organization, email, invited_user ):
            raise DuplicateInvitationError(
                'A pending invitation already exists for this email or user.'
            )
        return self.create(
            organization = organization,
            email_address = email,
            organization_role = role,
            invited_by = invited_by,
            invited_user = invited_user,
        )

    def _pending_exists( self,
                         organization : 'Organization',
                         email        : str,
                         invited_user : UserType        ) -> bool:
        pending = self.filter(
            organization = organization,
            status = OrganizationInvitationStatus.WAITING,
        )
        if ( email is not None ) and pending.filter( email_address__iexact = email ).exists():
            return True
        if ( invited_user is not None ) and pending.filter( invited_user = invited_user ).exists():
            return True
        return False
