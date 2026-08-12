import logging

from django.contrib.auth import get_user_model
from django.test import TestCase

from organization import deletion
from organization.enums import OrganizationInvitationStatus, OrganizationRole
from organization.exceptions import LastActiveOwnerError
from organization.models import Organization, OrganizationInvitation, OrganizationMember

logging.disable(logging.CRITICAL)

User = get_user_model()


def _user( email ):
    return User.objects.create_user( email = email )


def _add_member( org, user, role ):
    return OrganizationMember.objects.create(
        organization = org, user = user, organization_role = role )


def _member( org, user ):
    return OrganizationMember.objects.get( organization = org, user = user )


class IsSoleActiveOwnerTest(TestCase):

    def test_lone_owner_is_sole(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self.assertTrue( _member( org, user ).is_sole_active_owner )

    def test_co_owner_is_not_sole(self):
        u1, u2 = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( u1, 'A' )
        _add_member( org, u2, OrganizationRole.OWNER )
        self.assertFalse( _member( org, u1 ).is_sole_active_owner )

    def test_non_owner_is_not_sole(self):
        owner, member_user = _user( 'o@x.test' ), _user( 'm@x.test' )
        org = Organization.objects.create_for_owner( owner, 'A' )
        member = _add_member( org, member_user, OrganizationRole.MEMBER )
        self.assertFalse( member.is_sole_active_owner )

    def test_inactive_owner_is_not_sole(self):
        u1, u2 = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( u1, 'A' )
        _add_member( org, u2, OrganizationRole.OWNER )  # keeps the invariant when u1 deactivates
        member = _member( org, u1 )
        member.deactivate()
        self.assertFalse( member.is_sole_active_owner )


class DeleteOrganizationTest(TestCase):

    def test_deletes_org_with_members_and_invitations(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        OrganizationInvitation.objects.create(
            organization = org, email_address = 'invitee@x.test',
            organization_role = OrganizationRole.MEMBER,
            status = OrganizationInvitationStatus.WAITING )

        deletion.delete_organization( org )

        self.assertFalse( Organization.objects.filter( pk = org.pk ).exists() )
        self.assertFalse( OrganizationMember.objects.filter( organization_id = org.pk ).exists() )
        self.assertFalse( OrganizationInvitation.objects.filter( organization_id = org.pk ).exists() )


class LeaveOrganizationTest(TestCase):

    def test_co_owner_can_leave_and_org_persists(self):
        u1, u2 = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( u1, 'A' )
        _add_member( org, u2, OrganizationRole.OWNER )
        member1 = _member( org, u1 )

        deletion.leave_organization( member1 )

        self.assertFalse( OrganizationMember.objects.filter( pk = member1.pk ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )

    def test_sole_owner_cannot_leave(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        with self.assertRaises( LastActiveOwnerError ):
            deletion.leave_organization( _member( org, user ) )


class DeleteAccountTest(TestCase):

    def test_sole_owner_of_one_org_deletes_both(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )

        deletion.delete_account( user )

        self.assertFalse( User.objects.filter( pk = user.pk ).exists() )
        self.assertFalse( Organization.objects.filter( pk = org.pk ).exists() )

    def test_co_owner_leaves_and_org_persists_for_others(self):
        u1, u2 = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( u1, 'A' )
        _add_member( org, u2, OrganizationRole.OWNER )
        u1_id = u1.pk

        deletion.delete_account( u1 )

        self.assertFalse( User.objects.filter( pk = u1_id ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )
        self.assertTrue( OrganizationMember.objects.active_owners( org ).filter( user = u2 ).exists() )
        self.assertFalse( OrganizationMember.objects.filter( user_id = u1_id ).exists() )

    def test_non_owner_leaves_and_org_persists(self):
        owner, member_user = _user( 'o@x.test' ), _user( 'm@x.test' )
        org = Organization.objects.create_for_owner( owner, 'A' )
        _add_member( org, member_user, OrganizationRole.MEMBER )
        member_user_id = member_user.pk

        deletion.delete_account( member_user )

        self.assertFalse( User.objects.filter( pk = member_user_id ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )
        self.assertFalse( OrganizationMember.objects.filter( user_id = member_user_id ).exists() )

    def test_multi_org_mixed_dispositions(self):
        user = _user( 'a@x.test' )
        co_owner = _user( 'b@x.test' )
        other_owner = _user( 'c@x.test' )
        # A: user is the sole owner -> deleted with its data.
        org_a = Organization.objects.create_for_owner( user, 'A' )
        # B: user is a co-owner -> persists for the co-owner.
        org_b = Organization.objects.create_for_owner( co_owner, 'B' )
        _add_member( org_b, user, OrganizationRole.OWNER )
        # C: user is a plain member -> persists for its owner.
        org_c = Organization.objects.create_for_owner( other_owner, 'C' )
        _add_member( org_c, user, OrganizationRole.MEMBER )
        user_id = user.pk

        deletion.delete_account( user )

        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertFalse( Organization.objects.filter( pk = org_a.pk ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org_b.pk ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org_c.pk ).exists() )
        self.assertFalse( OrganizationMember.objects.filter( user_id = user_id ).exists() )
        # The surviving organizations still each retain an active owner.
        self.assertTrue( OrganizationMember.objects.active_owners( org_b ).exists() )
        self.assertTrue( OrganizationMember.objects.active_owners( org_c ).exists() )
