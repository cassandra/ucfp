"""forecast_overview: the dashboard forecast card's whole state for an organization.

A saved run always wins (it is immutable and always viewable, whatever the inputs look like now), so it is
recapped as HAS_RUN regardless of current readiness. Absent a saved run, the setup ladder the hub already
gates on decides the state -- a complete profile first, then a runnable scenario -- so the card routes to
the precise next step (NEEDS_PROFILE / NEEDS_SCENARIO) or invites the first run (READY_NO_RUNS).
"""
from datetime import datetime, timezone as tz

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.models import PlanningResultRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.overview import ForecastState, forecast_overview
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile


def _reviewed_keys_by_flow( profile ):
    """Every applicable, form-backed section key grouped by its owning flow -- so a record can mark exactly
    its own sections reviewed and the three together cover the whole interview (as `test_gating` does)."""
    by_flow = { 'profile': [], 'plans': [], 'assumptions': [] }
    for section in applicable_sections( profile ):
        if section.form is not None:
            by_flow[ flow_of( section ) ].append( section.key )
    return by_flow


class ForecastOverviewTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()        # expected_assumptions reads a seeded outlook
        self.org  = Organization.objects.create( name = 'Org' )
        self.keys = _reviewed_keys_by_flow( forecast_profile() )

    # -- profile / scenario builders -------------------------------------------------------------------

    def _complete_profile( self ):
        record = save_profile( self.org, forecast_profile() )
        record.acknowledged_sections = self.keys[ 'profile' ]   # walked -> a *complete* profile
        record.save()
        return record

    def _scenario( self, label, reviewed = True ):
        plans = PlansRecord( organization = self.org, label = f'{label} P',
                             acknowledged_sections = self.keys[ 'plans' ] if reviewed else [] )
        save_plans( plans, Plans() )
        assumptions = AssumptionsRecord( organization = self.org, label = f'{label} A',
                                         acknowledged_sections = self.keys[ 'assumptions' ] if reviewed else [] )
        save_assumptions( assumptions, expected_assumptions() )
        return create_scenario( self.org, plans, assumptions, label )

    def _saved_run( self, label = 'Run', usage_role = UsageRole.SAVED ):
        profile = load_profile( save_profile( self.org, forecast_profile() ) )
        run = run_and_capture(
            organization = self.org, profile = profile, plans = Plans(),
            assumptions = expected_assumptions(), frame = forecast_frame(), label = label )
        return PlanningResultRecord.objects.create(
            organization = self.org, feature = PlanningFeature.FINANCIAL_FORECAST,
            run = run, label = label, usage_role = usage_role )

    # -- setup ladder (no saved run) -------------------------------------------------------------------

    def test_no_complete_profile_needs_profile( self ):
        self.assertEqual( forecast_overview( self.org ).state, ForecastState.NEEDS_PROFILE )

    def test_complete_profile_but_no_scenario_needs_scenario( self ):
        self._complete_profile()
        overview = forecast_overview( self.org )
        self.assertEqual( overview.state, ForecastState.NEEDS_SCENARIO )
        self.assertIsNone( overview.build_scenario )            # nothing to resume or build toward

    def test_half_built_scenario_needs_scenario_and_offers_it_to_build( self ):
        self._complete_profile()
        scenario = self._scenario( 'Half', reviewed = False )
        overview = forecast_overview( self.org )
        self.assertEqual( overview.state, ForecastState.NEEDS_SCENARIO )
        self.assertEqual( overview.build_scenario.uuid, scenario.uuid )
        self.assertFalse( overview.build_scenario_started )    # created, never worked on

    def test_runnable_scenario_no_runs_is_ready( self ):
        self._complete_profile()
        self._scenario( 'Runnable' )
        self.assertEqual( forecast_overview( self.org ).state, ForecastState.READY_NO_RUNS )

    # -- a saved run wins ------------------------------------------------------------------------------

    def test_saved_run_is_recapped_with_its_card( self ):
        result   = self._saved_run( label = 'Baseline' )
        overview = forecast_overview( self.org )
        self.assertEqual( overview.state, ForecastState.HAS_RUN )
        card = overview.card
        self.assertEqual( card.run_uuid, result.run.uuid )
        self.assertEqual( card.label, 'Baseline' )
        # The support frame is 2026-2030 yearly; cash-only, so the plan lasts and ends solvent.
        self.assertEqual( ( card.start_year, card.end_year, card.duration_years ), ( 2026, 2030, 5 ) )
        self.assertEqual( card.age_span, 'age 66 → 70' )       # subject born 1960: 66 at 2026, 70 at 2030
        self.assertTrue( card.lasted )
        self.assertFalse( card.depleted )
        self.assertIsNone( card.ran_out_year )
        self.assertTrue( card.has_end_net_worth )
        self.assertEqual( card.start_net_worth, forecast_profile().assets[ 0 ].opening_value )

    def test_a_saved_run_wins_over_an_unbuilt_setup( self ):
        # Even with no complete profile now, an immutable saved run is still shown -- it is always viewable.
        self._saved_run()
        self.assertEqual( forecast_overview( self.org ).state, ForecastState.HAS_RUN )

    def test_a_working_run_does_not_count_as_a_saved_run( self ):
        # A transient/working run is not a saved result, so the card falls through to the setup ladder.
        self._complete_profile()
        self._scenario( 'Runnable' )
        self._saved_run( usage_role = UsageRole.WORKING )
        self.assertEqual( forecast_overview( self.org ).state, ForecastState.READY_NO_RUNS )

    def test_the_most_recent_saved_run_is_the_one_recapped( self ):
        older = self._saved_run( label = 'Older' )
        newer = self._saved_run( label = 'Newer' )
        # Pin the timestamps so ordering is deterministic regardless of creation speed.
        PlanningResultRecord.objects.filter( pk = older.pk ).update(
            created_datetime = datetime( 2026, 1, 1, tzinfo = tz.utc ) )
        PlanningResultRecord.objects.filter( pk = newer.pk ).update(
            created_datetime = datetime( 2026, 6, 1, tzinfo = tz.utc ) )
        self.assertEqual( forecast_overview( self.org ).card.run_uuid, newer.run.uuid )

    def test_the_run_is_scoped_to_the_organization( self ):
        self._saved_run()
        other = Organization.objects.create( name = 'Other' )
        self.assertEqual( forecast_overview( other ).state, ForecastState.NEEDS_PROFILE )
