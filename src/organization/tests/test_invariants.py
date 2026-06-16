from django.contrib.auth import get_user_model

from testing.base_test_case import BaseTestCase

from organization.enums import OrganizationRole
from organization.exceptions import LastActiveOwnerError
from organization.models import Organization, OrganizationMember


class LastActiveOwnerInvariantTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.owner_user = self.User.objects.create_user( email = 'owner@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.owner_user, name = 'Acme' )
        self.owner = self.organization.members.get()
        return

    def _add_member(self, email, role):
        user = self.User.objects.create_user( email = email, password = 'x' )
        return OrganizationMember.objects.create(
            organization = self.organization,
            user = user,
            organization_role = role,
        )

    def test_cannot_delete_sole_active_owner(self):
        with self.assertRaises( LastActiveOwnerError ):
            self.owner.delete()
        self.assertTrue( OrganizationMember.objects.filter( pk = self.owner.pk ).exists() )
        return

    def test_cannot_demote_sole_active_owner(self):
        self.owner.organization_role = OrganizationRole.MEMBER
        with self.assertRaises( LastActiveOwnerError ):
            self.owner.save()
        self.owner.refresh_from_db()
        self.assertEqual( self.owner.organization_role, OrganizationRole.OWNER )
        return

    def test_cannot_deactivate_sole_active_owner(self):
        self.owner.is_active = False
        with self.assertRaises( LastActiveOwnerError ):
            self.owner.save()
        self.owner.refresh_from_db()
        self.assertTrue( self.owner.is_active )
        return

    def test_can_delete_owner_when_another_active_owner_exists(self):
        self._add_member( 'owner2@example.com', OrganizationRole.OWNER )
        self.owner.delete()
        self.assertFalse( OrganizationMember.objects.filter( pk = self.owner.pk ).exists() )
        self.assertEqual( OrganizationMember.objects.active_owners( self.organization ).count(), 1 )
        return

    def test_can_demote_owner_when_another_active_owner_exists(self):
        self._add_member( 'owner2@example.com', OrganizationRole.OWNER )
        self.owner.organization_role = OrganizationRole.ADMIN
        self.owner.save()
        self.owner.refresh_from_db()
        self.assertEqual( self.owner.organization_role, OrganizationRole.ADMIN )
        return

    def test_deleting_non_owner_member_is_unaffected(self):
        member = self._add_member( 'member@example.com', OrganizationRole.MEMBER )
        member.delete()
        self.assertFalse( OrganizationMember.objects.filter( pk = member.pk ).exists() )
        return

    def test_inactive_second_owner_does_not_satisfy_invariant(self):
        second = self._add_member( 'owner2@example.com', OrganizationRole.OWNER )
        # Deactivating the second owner is allowed: the first is still active.
        second.is_active = False
        second.save()
        # The first owner is now the sole *active* owner, so it stays protected.
        with self.assertRaises( LastActiveOwnerError ):
            self.owner.delete()
        return

    def test_deactivate_helper_soft_leaves_a_member(self):
        member = self._add_member( 'member@example.com', OrganizationRole.MEMBER )
        member.deactivate()
        member.refresh_from_db()
        self.assertFalse( member.is_active )
        self.assertTrue( OrganizationMember.objects.filter( pk = member.pk ).exists() )
        return

    def test_deactivate_helper_blocks_last_active_owner(self):
        with self.assertRaises( LastActiveOwnerError ):
            self.owner.deactivate()
        self.owner.refresh_from_db()
        self.assertTrue( self.owner.is_active )
        return

    def test_promoting_a_member_to_owner_is_allowed(self):
        member = self._add_member( 'member@example.com', OrganizationRole.MEMBER )
        member.organization_role = OrganizationRole.OWNER
        member.save()
        member.refresh_from_db()
        self.assertEqual( member.organization_role, OrganizationRole.OWNER )
        self.assertEqual( OrganizationMember.objects.active_owners( self.organization ).count(), 2 )
        return
