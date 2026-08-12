from django.contrib.auth import get_user_model

from testing.base_test_case import BaseTestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember


class OrganizationProvisioningTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        return

    def test_create_for_owner_creates_sole_active_owner(self):
        user = self.User.objects.create_user( email = 'owner@example.com', password = 'x' )
        organization = Organization.objects.create_for_owner( user, name = 'Acme' )

        self.assertEqual( organization.name, 'Acme' )
        member = organization.members.get()
        self.assertEqual( member.user, user )
        self.assertEqual( member.organization_role, OrganizationRole.OWNER )
        self.assertTrue( member.is_active )
        return

    def test_create_for_email_creates_user_and_owned_organization(self):
        organization = Organization.objects.create_for_email( 'new@example.com', name = 'Globex' )

        user = self.User.objects.get( email = 'new@example.com' )
        member = organization.members.get()
        self.assertEqual( member.user, user )
        self.assertEqual( member.organization_role, OrganizationRole.OWNER )
        return

    def test_create_for_email_user_has_no_usable_password(self):
        Organization.objects.create_for_email( 'np@example.com', name = 'NoPass' )
        user = self.User.objects.get( email = 'np@example.com' )
        self.assertFalse( user.has_usable_password() )
        return


class OrganizationDisplayNameTestCase( BaseTestCase ):
    """`display_name` hides the auto-provisioned `user-<uuid>` name (meaningless
    to a person) behind a placeholder, while showing a real name verbatim."""

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        return

    def test_auto_provisioned_name_shows_a_placeholder(self):
        user = self.User.objects.create_user( email = 'u@example.com' )
        organization = Organization.objects.create_default_for_user( user )

        self.assertEqual( organization.name, f'user-{user.uuid}' )
        self.assertEqual( organization.display_name, 'Untitled household' )

    def test_user_chosen_name_is_shown_verbatim(self):
        organization = Organization.objects.create( name = 'Our Household' )
        self.assertEqual( organization.display_name, 'Our Household' )

    def test_name_that_merely_starts_with_user_is_not_treated_as_auto(self):
        # The recognizer requires a real UUID after the prefix, so an ordinary
        # name like this is shown as-is, not mistaken for an auto-provisioned one.
        organization = Organization.objects.create( name = 'user-group budget' )
        self.assertEqual( organization.display_name, 'user-group budget' )


class OrganizationMemberQueryTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.user = self.User.objects.create_user( email = 'u@example.com', password = 'x' )
        self.org_a = Organization.objects.create_for_owner( self.user, name = 'A' )
        self.org_b = Organization.objects.create( name = 'B' )
        OrganizationMember.objects.create(
            organization = self.org_b,
            user = self.user,
            organization_role = OrganizationRole.MEMBER,
        )
        return

    def test_for_user_returns_all_active_memberships(self):
        self.assertEqual( OrganizationMember.objects.for_user( self.user ).count(), 2 )
        return

    def test_for_user_excludes_inactive_memberships(self):
        membership = OrganizationMember.objects.get( organization = self.org_b, user = self.user )
        membership.is_active = False
        membership.save()
        self.assertEqual( OrganizationMember.objects.for_user( self.user ).count(), 1 )
        return

    def test_active_owners_returns_only_active_owner_rows(self):
        owners = OrganizationMember.objects.active_owners( self.org_a )
        self.assertEqual( owners.count(), 1 )
        self.assertEqual( owners.get().user, self.user )
        # The org_b membership is a MEMBER, not an owner.
        self.assertEqual( OrganizationMember.objects.active_owners( self.org_b ).count(), 0 )
        return
