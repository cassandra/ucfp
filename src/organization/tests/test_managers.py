import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

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

    def test_active_membership_for_returns_a_joined_membership(self):
        membership = OrganizationMember.objects.active_membership_for(
            self.user, str( self.org_b.uuid ) )
        self.assertIsNotNone( membership )
        self.assertEqual( membership.organization, self.org_b )
        return

    def test_active_membership_for_none_for_a_foreign_organization(self):
        stranger = self.User.objects.create_user( email = 'stranger@example.com' )
        foreign = Organization.objects.create_for_owner( stranger, name = 'Foreign' )
        self.assertIsNone(
            OrganizationMember.objects.active_membership_for( self.user, str( foreign.uuid ) ) )
        return

    def test_active_membership_for_none_when_membership_is_inactive(self):
        membership = OrganizationMember.objects.get( organization = self.org_b, user = self.user )
        membership.deactivate()
        self.assertIsNone(
            OrganizationMember.objects.active_membership_for( self.user, str( self.org_b.uuid ) ) )
        return

    def test_active_membership_for_none_for_an_unknown_uuid(self):
        self.assertIsNone(
            OrganizationMember.objects.active_membership_for( self.user, str( uuid.uuid4() ) ) )
        return

    def test_default_organization_for_prefers_the_owned_membership(self):
        # org_a is owned, org_b merely joined -> the owned one is the landing default.
        self.assertEqual(
            OrganizationMember.objects.default_organization_for( self.user ), self.org_a )
        return


class DefaultOrganizationForTestCase( BaseTestCase ):
    """`default_organization_for` picks a user's landing organization: one they own over
    one they merely joined, breaking ties by earliest creation; None when they belong to
    nothing."""

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        return

    def test_none_when_user_has_no_active_membership(self):
        user = self.User.objects.create_user( email = 'nobody@example.com' )
        self.assertIsNone( OrganizationMember.objects.default_organization_for( user ) )
        return

    def test_returns_the_sole_membership(self):
        user = self.User.objects.create_user( email = 'solo@example.com' )
        organization = Organization.objects.create_for_owner( user, name = 'Solo' )
        self.assertEqual(
            OrganizationMember.objects.default_organization_for( user ), organization )
        return

    def test_prefers_an_owned_organization_over_an_earlier_joined_one(self):
        # The joined org is created first, so only the role preference -- not recency -- can
        # make the owned org win.
        user = self.User.objects.create_user( email = 'member@example.com' )
        host = self.User.objects.create_user( email = 'host@example.com' )
        joined = Organization.objects.create_for_owner( host, name = 'Joined' )
        joined.members.create( user = user, organization_role = OrganizationRole.MEMBER )
        owned = Organization.objects.create_for_owner( user, name = 'Owned' )

        self.assertEqual(
            OrganizationMember.objects.default_organization_for( user ), owned )
        return

    def test_breaks_owned_ties_by_earliest_created(self):
        user = self.User.objects.create_user( email = 'multi@example.com' )
        first = Organization.objects.create_for_owner( user, name = 'First' )
        second = Organization.objects.create_for_owner( user, name = 'Second' )
        # created_datetime is auto_now_add, so pin the ordering explicitly (bypassing the auto
        # field via update) to make `second` the earliest-created despite being made later.
        Organization.objects.filter( pk = second.pk ).update(
            created_datetime = timezone.now() - timedelta( days = 2 ) )
        Organization.objects.filter( pk = first.pk ).update(
            created_datetime = timezone.now() - timedelta( days = 1 ) )

        self.assertEqual(
            OrganizationMember.objects.default_organization_for( user ), second )
        return

    def test_ignores_an_inactive_membership(self):
        user = self.User.objects.create_user( email = 'left@example.com' )
        host = self.User.objects.create_user( email = 'host2@example.com' )
        owned = Organization.objects.create_for_owner( user, name = 'Owned' )
        left = Organization.objects.create_for_owner( host, name = 'Left' )
        membership = left.members.create( user = user, organization_role = OrganizationRole.MEMBER )
        membership.deactivate()

        self.assertEqual(
            OrganizationMember.objects.default_organization_for( user ), owned )
        return
