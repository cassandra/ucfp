"""`seed_sample_org`: stand up the sample household (superuser-owned) from the committed fixture with a
captured forecast; idempotent, with `--force` refreshing the data while preserving the org + memberships.

The fast tests validate that the fixture loads into correct, *runnable* records and cover the guard paths
that return before the (slow) forecast. The actual forecast generation is exercised under the `e2e` tag,
which the frequently-run suite excludes.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, tag
from django.utils import timezone

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.models import ProfileRecord, ScenarioRecord
from ucfp.inputs.profile.repository import latest_profile
from ucfp.inputs.state import completed_profile
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.gating import partition_scenarios
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord

from ucfp.onboarding.constants import (
    SAMPLE_FORECAST_NAME, SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID, SAMPLE_SCENARIO_NAME,
    SAMPLE_SCENARIO_UUID )
from ucfp.onboarding.seeding import NoSuperuserError, _seed_records, seed_sample_org

User = get_user_model()


def _sample_org():
    return Organization.objects.get( uuid = SAMPLE_ORGANIZATION_UUID )


class SeedRecordsFromFixtureTest( TestCase ):
    """The committed fixture loads into correct, runnable records -- without running the forecast."""

    def test_seeds_a_runnable_profile_and_scenario_from_the_fixture( self ):
        organization = Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

        profile_record, scenario = _seed_records( organization )

        self.assertIsNotNone( completed_profile( organization ) )       # profile is complete
        self.assertTrue( profile_record.acknowledged_sections )         # review state carried
        self.assertEqual(
            profile_record.effective_date, date( timezone.localdate().year, 1, 1 ) )  # January boundary
        self.assertEqual( scenario.uuid, SAMPLE_SCENARIO_UUID )
        self.assertEqual( scenario.plans.organization_id, organization.pk )
        # The whole scenario is runnable now (profile + plans + assumptions complete, no drift).
        complete, _drift, _in_progress = partition_scenarios( organization, profile_record )
        self.assertIn( scenario.uuid, [ runnable.uuid for runnable in complete ] )


class SeedSampleOrgGuardsTest( TestCase ):
    """The guard/idempotency paths that resolve before the forecast (so these stay fast)."""

    def setUp( self ):
        self.superuser = User.objects.create_superuser( email = 'admin@x.test', password = 'x' )

    def test_re_seed_without_force_is_preserved( self ):
        organization, _ = Organization.objects.get_or_create(
            uuid = SAMPLE_ORGANIZATION_UUID, defaults = { 'name': SAMPLE_ORGANIZATION_NAME } )
        _seed_records( organization )                                   # already seeded (no forecast)

        result = seed_sample_org()                                      # sees the scenario -> preserved

        self.assertEqual( result.action, 'preserved' )
        self.assertEqual( ScenarioRecord.objects.filter( organization = organization ).count(), 1 )
        self.assertEqual( ProfileRecord.objects.filter( organization = organization ).count(), 1 )

    def test_requires_a_superuser( self ):
        User.objects.filter( is_superuser = True ).delete()
        with self.assertRaises( NoSuperuserError ):
            seed_sample_org()

    def test_command_errors_without_a_superuser( self ):
        User.objects.filter( is_superuser = True ).delete()
        with self.assertRaises( CommandError ):
            call_command( 'seed_sample_org', verbosity = 0 )


@tag( 'e2e' )
class SeedSampleOrgForecastTest( TestCase ):
    """The full seed including the real forecast run -- slow, so excluded from the frequent suite."""

    def setUp( self ):
        seed_default_parameter_sets()                        # the forecast run needs the seeded law/outlook
        self.superuser = User.objects.create_superuser( email = 'admin@x.test', password = 'x' )

    def test_seeds_the_sample_household_with_a_forecast( self ):
        result = seed_sample_org()

        self.assertEqual( result.action, 'created' )
        organization = _sample_org()
        self.assertEqual( organization.name, SAMPLE_ORGANIZATION_NAME )
        self.assertTrue( OrganizationMember.objects.filter(
            organization = organization, user = self.superuser,
            organization_role = OrganizationRole.OWNER, is_active = True ).exists() )
        self.assertIsNotNone( completed_profile( organization ) )
        run = ProjectionRunRecord.objects.get( organization = organization )
        self.assertEqual( run.label, SAMPLE_FORECAST_NAME )                 # titled, not timestamped
        self.assertEqual( run.source_label, SAMPLE_SCENARIO_NAME )          # scenario kept as provenance
        self.assertTrue( PlanningResultRecord.objects.filter(
            organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST ).exists() )

    def test_force_refreshes_data_but_preserves_the_org_and_memberships( self ):
        seed_sample_org()
        organization = _sample_org()
        viewer = User.objects.create_user( email = 'viewer@x.test' )
        OrganizationMember.objects.create(
            organization = organization, user = viewer, organization_role = OrganizationRole.VIEWER )
        first_run = ProjectionRunRecord.objects.get( organization = organization )

        result = seed_sample_org( force = True )

        self.assertEqual( result.action, 'refreshed' )
        self.assertEqual( _sample_org().pk, organization.pk )                          # same org
        self.assertTrue( OrganizationMember.objects.filter(                           # viewer kept
            organization = organization, user = viewer ).exists() )
        self.assertFalse( ProjectionRunRecord.objects.filter( pk = first_run.pk ).exists() )  # refreshed
        self.assertEqual( ProjectionRunRecord.objects.filter( organization = organization ).count(), 1 )

    def test_command_seeds_the_sample_household( self ):
        call_command( 'seed_sample_org', verbosity = 0 )
        self.assertTrue( latest_profile( _sample_org() ) is not None )
