from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.onboarding import reconciliation_service as service
from ucfp.onboarding.constants import EXAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.membership import join_example_org, working_organization

User = get_user_model()


def _guest_with_org():
    guest = User.objects.create_guest()
    Organization.objects.create_for_owner( guest, 'Household' )
    return guest


def _verified_with_org( email ):
    user = User.objects.create_user( email = email )
    Organization.objects.create_for_owner( user, 'Household' )
    return user


def _example_org_with_content():
    """The seeded, read-only example org (reserved UUID) with a populated Profile and its own owner --
    the shared preview every visitor is a VIEWER of, which reconciliation must never mistake for a
    Guest's own work nor touch when resolving a collision."""
    owner = User.objects.create_user( email = 'example-owner@example.com' )
    organization = Organization.objects.create(
        name = 'Example Household', uuid = EXAMPLE_ORGANIZATION_UUID )
    organization.members.create( user = owner, organization_role = OrganizationRole.OWNER )
    save_profile( organization, Profile(
        subjects = [ SubjectProfile( handle = 'subject', name = 'Sample Household',
                                     birthdate = date( 1980, 1, 1 ) ) ] ) )
    return organization


class OrganizationSummaryTest(TestCase):

    def test_no_profile_summarizes_to_empty(self):
        summary = service.organization_summary( working_organization( _guest_with_org() ) )
        self.assertFalse( summary.has_content )

    def test_named_subjects_and_funded_accounts_are_summarized(self):
        organization = working_organization( _guest_with_org() )
        save_profile( organization, Profile(
            subjects = [ SubjectProfile( handle = 'subject', name = 'Alice',
                                         birthdate = date( 1980, 1, 1 ) ) ],
            assets = [ AssetProfile( handle = 'cash', name = 'Checking', asset_class = AssetClass.CASH,
                                     opening_value = Decimal( '1500' ) ) ],
        ) )

        summary = service.organization_summary( organization )

        self.assertTrue( summary.has_content )
        self.assertEqual( [ 'Alice' ], summary.subject_names )
        self.assertEqual( [ ( 'Checking', Decimal( '1500' ) ) ], summary.accounts )

    def test_blank_names_and_zero_balances_are_not_content(self):
        organization = working_organization( _guest_with_org() )
        save_profile( organization, Profile(
            subjects = [ SubjectProfile( handle = 'subject', name = '  ',
                                         birthdate = date( 1980, 1, 1 ) ) ],
            assets = [ AssetProfile( handle = 'ira', name = 'IRA', asset_class = AssetClass.CASH,
                                     opening_value = Decimal( '0' ) ) ],
        ) )

        self.assertFalse( service.organization_summary( organization ).has_content )


class HasPlanContentTest(TestCase):
    """`has_plan_content` -- the shared "is there anything worth keeping?" predicate the collision flow and
    the dashboard's accidental-Guest sign-in offer both key on. It is the `has_content` of the org's summary,
    with None (no own org) reading as empty."""

    def test_false_for_no_organization(self):
        self.assertFalse( service.has_plan_content( None ) )

    def test_false_for_an_empty_org(self):
        self.assertFalse( service.has_plan_content( working_organization( _guest_with_org() ) ) )

    def test_true_once_a_named_subject_exists(self):
        organization = working_organization( _guest_with_org() )
        save_profile( organization, Profile( subjects = [ SubjectProfile(
            handle = 'subject', name = 'Alice', birthdate = date( 1980, 1, 1 ) ) ] ) )

        self.assertTrue( service.has_plan_content( organization ) )


class ReconciliationOpsTest(TestCase):

    def test_keep_current_rehomes_guest_org_and_drops_the_guest(self):
        guest = _guest_with_org()
        target = _verified_with_org( 'e@example.com' )
        guest_org = working_organization( guest )
        previous_org = working_organization( target )

        service.keep_current_discard_previous( guest, target )

        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )
        self.assertEqual( guest_org, working_organization( target ) )      # target now owns the work
        self.assertEqual( 0, OrganizationMember.objects.filter( organization = previous_org ).count() )
        self.assertTrue( Organization.objects.filter( pk = previous_org.pk ).exists() )   # orphaned, retained

    def test_discard_current_keeps_target_org_and_orphans_the_guest_org(self):
        guest = _guest_with_org()
        target = _verified_with_org( 'e@example.com' )
        guest_org = working_organization( guest )
        target_org = working_organization( target )

        service.discard_current_keep_previous( guest, target )

        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )
        self.assertEqual( target_org, working_organization( target ) )     # target keeps its own plan
        self.assertEqual( 0, OrganizationMember.objects.filter( organization = guest_org ).count() )
        self.assertTrue( Organization.objects.filter( pk = guest_org.pk ).exists() )      # orphaned, retained


class ExampleOrgIsNeverAPartyTest(TestCase):
    """The read-only example org (which every visitor is a VIEWER of once they tour) must never be
    mistaken for a Guest's own work nor touched when a collision is resolved -- its populated Profile
    would otherwise read as content, and re-homing/orphaning it would corrupt the shared preview."""

    @staticmethod
    def _member_ids( organization ):
        return set( OrganizationMember.objects.filter(
            organization = organization ).values_list( 'user_id', flat = True ) )

    def test_view_only_guest_summarizes_to_empty(self):
        # A Guest whose sole membership is the example VIEWER has no own work, despite the example's
        # populated Profile -- so no false collision is raised.
        _example_org_with_content()
        guest = User.objects.create_guest()
        join_example_org( guest )

        summary = service.organization_summary( working_organization( guest ) )

        self.assertFalse( summary.has_content )

    def test_keep_current_rehomes_the_own_org_and_leaves_the_example_untouched(self):
        example = _example_org_with_content()
        example_members = self._member_ids( example )
        guest = _guest_with_org()
        guest_org = working_organization( guest )       # the own org, not the example
        join_example_org( guest )                        # ...even though the Guest also views the example
        target = _verified_with_org( 'e@example.com' )

        service.keep_current_discard_previous( guest, target )

        self.assertNotEqual( EXAMPLE_ORGANIZATION_UUID, guest_org.uuid )
        self.assertEqual( guest_org, working_organization( target ) )     # target owns the Guest's own work
        self.assertEqual( example_members, self._member_ids( example ) )  # example ownership untouched

    def test_discard_leaves_the_example_untouched(self):
        example = _example_org_with_content()
        example_members = self._member_ids( example )
        guest = _guest_with_org()
        join_example_org( guest )
        target = _verified_with_org( 'e@example.com' )

        service.discard_current_keep_previous( guest, target )

        self.assertEqual( example_members, self._member_ids( example ) )
