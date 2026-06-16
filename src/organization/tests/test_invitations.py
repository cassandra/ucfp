from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from testing.base_test_case import BaseTestCase

from organization.enums import OrganizationInvitationStatus, OrganizationRole
from organization.exceptions import (
    AlreadyActiveMemberError,
    DuplicateInvitationError,
    InvitationRecipientMismatchError,
    InvitationStateError,
)
from organization.models import Organization, OrganizationInvitation, OrganizationMember


class InvitationCreationTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.inviter = self.User.objects.create_user( email = 'inviter@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.inviter, name = 'Acme' )
        return

    def test_invite_by_email_creates_waiting_invitation(self):
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'new@example.com',
        )
        self.assertEqual( invitation.status, OrganizationInvitationStatus.WAITING )
        self.assertEqual( invitation.email_address, 'new@example.com' )
        self.assertEqual( invitation.organization_role, OrganizationRole.MEMBER )
        self.assertEqual( invitation.invited_by, self.inviter )
        self.assertIsNone( invitation.invited_user )
        return

    def test_invite_by_email_links_existing_user_case_insensitive(self):
        existing = self.User.objects.create_user( email = 'Existing@example.com', password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'existing@example.com',
        )
        self.assertEqual( invitation.invited_user, existing )
        return

    def test_invite_by_user_without_email(self):
        target = self.User.objects.create_user( email = None, password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, invited_user = target,
        )
        self.assertEqual( invitation.invited_user, target )
        self.assertIsNone( invitation.email_address )
        return

    def test_invite_requires_email_or_user(self):
        with self.assertRaises( ValueError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, self.inviter,
            )
        return

    def test_invite_requires_invited_by(self):
        with self.assertRaises( ValueError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, None, email = 'x@example.com',
            )
        return

    def test_invite_rejects_active_member_by_email(self):
        with self.assertRaises( AlreadyActiveMemberError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, self.inviter, email = 'inviter@example.com',
            )
        return

    def test_invite_rejects_active_member_by_user(self):
        with self.assertRaises( AlreadyActiveMemberError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, self.inviter, invited_user = self.inviter,
            )
        return

    def test_duplicate_pending_email_rejected(self):
        OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'dup@example.com',
        )
        with self.assertRaises( DuplicateInvitationError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, self.inviter, email = 'DUP@example.com',
            )
        return

    def test_duplicate_pending_user_rejected(self):
        target = self.User.objects.create_user( email = None, password = 'x' )
        OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, invited_user = target,
        )
        with self.assertRaises( DuplicateInvitationError ):
            OrganizationInvitation.objects.invite(
                self.organization, OrganizationRole.MEMBER, self.inviter, invited_user = target,
            )
        return

    def test_reinvite_allowed_after_decline(self):
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'again@example.com',
        )
        invitation.decline()
        reinvite = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'again@example.com',
        )
        self.assertEqual( reinvite.status, OrganizationInvitationStatus.WAITING )
        return


class InvitationDatabaseConstraintTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.inviter = self.User.objects.create_user( email = 'inviter@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.inviter, name = 'Acme' )
        return

    def test_check_constraint_requires_email_or_user(self):
        with self.assertRaises( IntegrityError ):
            with transaction.atomic():
                OrganizationInvitation.objects.create(
                    organization = self.organization,
                    organization_role = OrganizationRole.MEMBER,
                )
        return

    def test_db_rejects_two_pending_invites_for_same_email(self):
        OrganizationInvitation.objects.create(
            organization = self.organization,
            email_address = 'c@example.com',
            organization_role = OrganizationRole.MEMBER,
        )
        with self.assertRaises( IntegrityError ):
            with transaction.atomic():
                OrganizationInvitation.objects.create(
                    organization = self.organization,
                    email_address = 'c@example.com',
                    organization_role = OrganizationRole.MEMBER,
                )
        return


class InvitationAcceptTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.inviter = self.User.objects.create_user( email = 'inviter@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.inviter, name = 'Acme' )
        return

    def test_accept_by_email_creates_active_member_with_role(self):
        invitee = self.User.objects.create_user( email = 'join@example.com', password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.ADMIN, self.inviter, email = 'join@example.com',
        )
        member = invitation.accept( invitee )
        self.assertTrue( member.is_active )
        self.assertEqual( member.organization_role, OrganizationRole.ADMIN )
        invitation.refresh_from_db()
        self.assertEqual( invitation.status, OrganizationInvitationStatus.ACCEPTED )
        self.assertEqual( invitation.invited_user, invitee )
        return

    def test_accept_by_user_identity_without_email(self):
        target = self.User.objects.create_user( email = None, password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, invited_user = target,
        )
        member = invitation.accept( target )
        self.assertEqual( member.user, target )
        return

    def test_accept_rejects_user_who_is_not_the_recipient(self):
        intruder = self.User.objects.create_user( email = 'intruder@example.com', password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'join@example.com',
        )
        with self.assertRaises( InvitationRecipientMismatchError ):
            invitation.accept( intruder )
        return

    def test_accept_on_non_waiting_is_rejected(self):
        invitee = self.User.objects.create_user( email = 'join@example.com', password = 'x' )
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'join@example.com',
        )
        invitation.accept( invitee )
        with self.assertRaises( InvitationStateError ):
            invitation.accept( invitee )
        return

    def test_accept_reactivates_inactive_member(self):
        invitee = self.User.objects.create_user( email = 'join@example.com', password = 'x' )
        member = OrganizationMember.objects.create(
            organization = self.organization,
            user = invitee,
            organization_role = OrganizationRole.MEMBER,
        )
        member.deactivate()
        invitation = OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 'join@example.com',
        )
        reactivated = invitation.accept( invitee )
        self.assertEqual( reactivated.pk, member.pk )
        self.assertTrue( reactivated.is_active )
        return

    def test_accept_is_idempotent_and_leaves_existing_role_unchanged(self):
        invitee = self.User.objects.create_user( email = 'join@example.com', password = 'x' )
        member = OrganizationMember.objects.create(
            organization = self.organization,
            user = invitee,
            organization_role = OrganizationRole.MEMBER,
        )
        # Build the invitation directly (with a different role) to bypass the
        # active-member guard in invite() and exercise accept()'s idempotency.
        invitation = OrganizationInvitation.objects.create(
            organization = self.organization,
            email_address = 'join@example.com',
            organization_role = OrganizationRole.ADMIN,
        )
        result = invitation.accept( invitee )
        self.assertEqual( result.pk, member.pk )
        result.refresh_from_db()
        self.assertEqual( result.organization_role, OrganizationRole.MEMBER )
        return


class InvitationTransitionTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.inviter = self.User.objects.create_user( email = 'inviter@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.inviter, name = 'Acme' )
        return

    def _invite(self):
        return OrganizationInvitation.objects.invite(
            self.organization, OrganizationRole.MEMBER, self.inviter, email = 't@example.com',
        )

    def test_decline_transitions_to_declined(self):
        invitation = self._invite()
        invitation.decline()
        invitation.refresh_from_db()
        self.assertEqual( invitation.status, OrganizationInvitationStatus.DECLINED )
        return

    def test_revoke_transitions_to_revoked(self):
        invitation = self._invite()
        invitation.revoke()
        invitation.refresh_from_db()
        self.assertEqual( invitation.status, OrganizationInvitationStatus.REVOKED )
        return

    def test_decline_on_non_waiting_is_rejected(self):
        invitation = self._invite()
        invitation.revoke()
        with self.assertRaises( InvitationStateError ):
            invitation.decline()
        return
