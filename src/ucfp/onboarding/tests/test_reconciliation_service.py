from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from organization.models import Organization, OrganizationMember

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.onboarding import reconciliation_service as service

User = get_user_model()


def _guest_with_org():
    guest = User.objects.create_guest()
    Organization.objects.create_for_owner( guest, 'Household' )
    return guest


def _verified_with_org( email ):
    user = User.objects.create_user( email = email )
    Organization.objects.create_for_owner( user, 'Household' )
    return user


class OrganizationSummaryTest(TestCase):

    def test_no_profile_summarizes_to_empty(self):
        summary = service.organization_summary( service.sole_organization( _guest_with_org() ) )
        self.assertFalse( summary.has_content )

    def test_named_subjects_and_funded_accounts_are_summarized(self):
        organization = service.sole_organization( _guest_with_org() )
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
        organization = service.sole_organization( _guest_with_org() )
        save_profile( organization, Profile(
            subjects = [ SubjectProfile( handle = 'subject', name = '  ',
                                         birthdate = date( 1980, 1, 1 ) ) ],
            assets = [ AssetProfile( handle = 'ira', name = 'IRA', asset_class = AssetClass.CASH,
                                     opening_value = Decimal( '0' ) ) ],
        ) )

        self.assertFalse( service.organization_summary( organization ).has_content )


class ReconciliationOpsTest(TestCase):

    def test_keep_current_rehomes_guest_org_and_drops_the_guest(self):
        guest = _guest_with_org()
        target = _verified_with_org( 'e@example.com' )
        guest_org = service.sole_organization( guest )
        previous_org = service.sole_organization( target )

        service.keep_current_discard_previous( guest, target )

        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )
        self.assertEqual( guest_org, service.sole_organization( target ) )      # target now owns the work
        self.assertEqual( 0, OrganizationMember.objects.filter( organization = previous_org ).count() )
        self.assertTrue( Organization.objects.filter( pk = previous_org.pk ).exists() )   # orphaned, retained

    def test_discard_current_keeps_target_org_and_orphans_the_guest_org(self):
        guest = _guest_with_org()
        target = _verified_with_org( 'e@example.com' )
        guest_org = service.sole_organization( guest )
        target_org = service.sole_organization( target )

        service.discard_current_keep_previous( guest, target )

        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )
        self.assertEqual( target_org, service.sole_organization( target ) )     # target keeps its own plan
        self.assertEqual( 0, OrganizationMember.objects.filter( organization = guest_org ).count() )
        self.assertTrue( Organization.objects.filter( pk = guest_org.pk ).exists() )      # orphaned, retained
