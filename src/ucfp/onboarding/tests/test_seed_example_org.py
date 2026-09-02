"""`seed_example_org`: stand up the example household (superuser-owned) from the committed fixture with a
captured forecast; idempotent, with `--force` refreshing the data while preserving the org + memberships.

The fast tests validate that the fixture loads into correct, *runnable* records and cover the guard paths
that return before the (slow) forecast. The actual forecast generation is exercised under the `e2e` tag,
which the frequently-run suite excludes.
"""
from datetime import date, datetime, timezone as datetime_timezone

import time_machine
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, tag
from django.utils import timezone

from common.datetime_utils import today_utc

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.models import (
    AssumptionsRecord, PlansRecord, ProfileRecord, ScenarioExploration, ScenarioRecord )
from ucfp.inputs.plans.repository import load_plans
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.state import completed_profile
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.gating import partition_scenarios
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord

from ucfp.onboarding.constants import (
    EXAMPLE_FORECAST_NAME, EXAMPLE_ORGANIZATION_NAME, EXAMPLE_ORGANIZATION_UUID, EXAMPLE_SCENARIO_NAME,
    EXAMPLE_SCENARIO_UUID )
from ucfp.onboarding.seeding import (
    NoSuperuserError, _clear_example_data, _fixture_matches, _is_current, _seed_records, seed_example_org )

# Every org-scoped data model the seed creates -- `_clear_example_data` must leave none of them behind.
_DATA_MODELS = (
    ProfileRecord, PlansRecord, AssumptionsRecord, ScenarioRecord,
    ProjectionRunRecord, PlanningResultRecord, BooksOfAccountRecord, ScenarioExploration )

User = get_user_model()


def _example_org():
    return Organization.objects.get( uuid = EXAMPLE_ORGANIZATION_UUID )


class SeedRecordsFromFixtureTest( TestCase ):
    """The committed fixture loads into correct, runnable records -- without running the forecast."""

    def test_seeds_a_runnable_profile_and_scenario_from_the_fixture( self ):
        organization = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )

        profile_record, scenario = _seed_records( organization )

        self.assertIsNotNone( completed_profile( organization ) )       # profile is complete
        self.assertTrue( profile_record.acknowledged_sections )         # review state carried
        self.assertEqual(
            profile_record.effective_date, date( today_utc().year, 1, 1 ) )  # January boundary, UTC year
        self.assertEqual( scenario.uuid, EXAMPLE_SCENARIO_UUID )
        self.assertEqual( scenario.plans.organization_id, organization.pk )
        # The whole scenario is runnable now (profile + plans + assumptions complete, no drift).
        complete, _drift, _in_progress = partition_scenarios( organization, profile_record )
        self.assertIn( scenario.uuid, [ runnable.uuid for runnable in complete ] )
        # The example loans carry contract-term facts and their plan snapshots (the loan-solver path), so
        # the fixture exercises them and a re-dump that dropped them would be caught here.
        self.assertTrue( any( debt.terms is not None for debt in load_profile( profile_record ).debts ) )
        self.assertTrue( load_plans( scenario.plans ).loan_terms_snapshots )

    def test_the_seed_year_is_the_utc_year_at_a_year_boundary( self ):
        # Regression for #246: 03:00 UTC on Jan 1 is still Dec 31 of the prior year across the Americas.
        # The seed's January-boundary date must take the UTC year, not the active zone's, or a seed run in
        # that window would date the example household a year behind.
        organization = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        with time_machine.travel( datetime( 2026, 1, 1, 3, 0, tzinfo = datetime_timezone.utc ) ):
            with timezone.override( 'America/Chicago' ):   # still 2025-12-31 locally
                profile_record, _scenario = _seed_records( organization )
        self.assertEqual( profile_record.effective_date, date( 2026, 1, 1 ) )


class FixtureMatchTest( TestCase ):
    """The content-aware refresh signal: seeded records match the fixture until something drifts."""

    def _seeded_org( self ):
        organization = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        _seed_records( organization )
        return organization

    def test_a_fresh_seed_matches_the_fixture( self ):
        self.assertTrue( _fixture_matches( self._seeded_org() ) )

    def test_missing_records_do_not_match( self ):
        organization = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )  # no records seeded
        self.assertFalse( _fixture_matches( organization ) )

    def test_drifted_review_state_no_longer_matches( self ):
        organization = self._seeded_org()
        profile = latest_profile( organization )
        profile.acknowledged_sections = []                   # an edit the value-diff would not even see
        profile.save()
        self.assertFalse( _fixture_matches( organization ) )

    def test_drifted_data_no_longer_matches( self ):
        organization = self._seeded_org()
        scenario = ScenarioRecord.objects.get( uuid = EXAMPLE_SCENARIO_UUID )
        plans = scenario.plans
        plans.data = { **plans.data, '_edited': True }       # any structural/value change trips the compare
        plans.save()
        self.assertFalse( _fixture_matches( organization ) )

    def test_matching_records_are_not_current_without_a_captured_forecast( self ):
        # The F1 gate: records equal to the fixture are still not "current" until the run is captured, so a
        # re-seed regenerates a run lost to a mid-seed forecast failure instead of reporting 'preserved'.
        organization = self._seeded_org()
        self.assertTrue( _fixture_matches( organization ) )
        self.assertFalse( _is_current( organization ) )


class ClearExampleDataTest( TestCase ):
    """`_clear_example_data` leaves no org-scoped data behind (a guard so a future model is not missed),
    while keeping the org and its memberships."""

    def test_clears_every_data_model_but_keeps_the_org_and_memberships( self ):
        organization = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        member = User.objects.create_user( email = 'member@x.test' )
        OrganizationMember.objects.create(
            organization = organization, user = member, organization_role = OrganizationRole.OWNER )
        _seed_records( organization )

        _clear_example_data( organization )

        for model in _DATA_MODELS:
            self.assertEqual(
                model.objects.filter( organization = organization ).count(), 0, model.__name__ )
        self.assertTrue( Organization.objects.filter( uuid = EXAMPLE_ORGANIZATION_UUID ).exists() )
        self.assertTrue( OrganizationMember.objects.filter(
            organization = organization, user = member ).exists() )


class SeedExampleOrgGuardsTest( TestCase ):
    """The guard paths that resolve before the forecast (so these stay fast)."""

    def setUp( self ):
        self.superuser = User.objects.create_superuser( email = 'admin@x.test', password = 'x' )

    def test_requires_a_superuser( self ):
        User.objects.filter( is_superuser = True ).delete()
        with self.assertRaises( NoSuperuserError ):
            seed_example_org()

    def test_command_errors_without_a_superuser( self ):
        User.objects.filter( is_superuser = True ).delete()
        with self.assertRaises( CommandError ):
            call_command( 'seed_example_org', verbosity = 0 )


@tag( 'e2e' )
class SeedExampleOrgForecastTest( TestCase ):
    """The full seed including the real forecast run -- slow, so excluded from the frequent suite."""

    def setUp( self ):
        seed_default_parameter_sets()                        # the forecast run needs the seeded law/outlook
        self.superuser = User.objects.create_superuser( email = 'admin@x.test', password = 'x' )

    def test_seeds_the_example_household_with_a_forecast( self ):
        result = seed_example_org()

        self.assertEqual( result.action, 'created' )
        organization = _example_org()
        self.assertEqual( organization.name, EXAMPLE_ORGANIZATION_NAME )
        self.assertTrue( OrganizationMember.objects.filter(
            organization = organization, user = self.superuser,
            organization_role = OrganizationRole.OWNER, is_active = True ).exists() )
        self.assertIsNotNone( completed_profile( organization ) )
        run = ProjectionRunRecord.objects.get( organization = organization )
        self.assertEqual( run.label, EXAMPLE_FORECAST_NAME )                 # titled, not timestamped
        self.assertEqual( run.source_label, EXAMPLE_SCENARIO_NAME )          # scenario kept as provenance
        self.assertTrue( PlanningResultRecord.objects.filter(
            organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST ).exists() )

    def test_force_refreshes_data_but_preserves_the_org_and_memberships( self ):
        seed_example_org()
        organization = _example_org()
        viewer = User.objects.create_user( email = 'viewer@x.test' )
        OrganizationMember.objects.create(
            organization = organization, user = viewer, organization_role = OrganizationRole.VIEWER )
        first_run = ProjectionRunRecord.objects.get( organization = organization )

        result = seed_example_org( force = True )

        self.assertEqual( result.action, 'refreshed' )
        self.assertEqual( _example_org().pk, organization.pk )                          # same org
        self.assertTrue( OrganizationMember.objects.filter(                           # viewer kept
            organization = organization, user = viewer ).exists() )
        self.assertFalse( ProjectionRunRecord.objects.filter( pk = first_run.pk ).exists() )  # refreshed
        # A refresh clears before re-seeding, so nothing accumulates: exactly one of each data record.
        self.assertEqual( ScenarioExploration.objects.filter( organization = organization ).count(), 0 )
        for model in ( ProfileRecord, PlansRecord, AssumptionsRecord, ScenarioRecord,
                       ProjectionRunRecord, PlanningResultRecord, BooksOfAccountRecord ):
            self.assertEqual(
                model.objects.filter( organization = organization ).count(), 1, model.__name__ )

    def test_re_seed_when_unchanged_is_preserved( self ):
        seed_example_org()
        organization = _example_org()
        run = ProjectionRunRecord.objects.get( organization = organization )

        result = seed_example_org()                                      # fixture unchanged + run present

        self.assertEqual( result.action, 'preserved' )
        self.assertEqual( ProjectionRunRecord.objects.get( organization = organization ).pk, run.pk )
        self.assertEqual( ProfileRecord.objects.filter( organization = organization ).count(), 1 )

    def test_re_seed_regenerates_a_missing_forecast_run( self ):
        # F1: records still match the fixture but the captured run is gone (a mid-seed forecast failure).
        # A plain re-seed must self-heal by regenerating it, not report 'preserved'.
        seed_example_org()
        organization = _example_org()
        PlanningResultRecord.objects.filter( organization = organization ).delete()
        ProjectionRunRecord.objects.filter( organization = organization ).delete()
        self.assertTrue( _fixture_matches( organization ) )            # records untouched

        result = seed_example_org()

        self.assertEqual( result.action, 'refreshed' )
        self.assertTrue( PlanningResultRecord.objects.filter(
            organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST ).exists() )

    def test_re_seed_with_changed_data_refreshes_and_replaces_the_run( self ):
        seed_example_org()
        organization = _example_org()
        old_run = ProjectionRunRecord.objects.get( organization = organization )
        # Make the stored profile drift from the fixture, standing in for a newer dumped fixture; a plain
        # re-seed (no --force) should detect the delta, rebuild, and replace the run.
        profile = latest_profile( organization )
        profile.acknowledged_sections = []
        profile.save()

        result = seed_example_org()

        self.assertEqual( result.action, 'refreshed' )
        self.assertFalse( ProjectionRunRecord.objects.filter( pk = old_run.pk ).exists() )  # old run gone
        run = ProjectionRunRecord.objects.get( organization = organization )                # exactly one
        self.assertEqual( run.label, EXAMPLE_FORECAST_NAME )

    def test_command_seeds_the_example_household( self ):
        call_command( 'seed_example_org', verbosity = 0 )
        self.assertTrue( latest_profile( _example_org() ) is not None )
