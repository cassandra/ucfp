"""FinancialForecastView._live_resume: the hub's resume-exploration notice.

It is suppressed when the exploration has drifted against the current profile -- either the `source`
scenario it is anchored to (the one the notice names and the drift block flags) or its `working` copy
references something the profile no longer has. The regression: the check was on the working copy only,
so an exploration of a drift-blocked *source* (whose working copy was a clean older clone) still offered
Resume alongside the block telling the user to reconcile that very scenario.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.exploration import enter_exploration, scenario_exploration
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.state import completed_profile
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.frames import FORECAST_MIN_YEARS, default_forecast_duration_years
from ucfp.planning.tests.support import expected_assumptions, forecast_profile
from ucfp.planning.views import FinancialForecastView


class LiveResumeTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()    # expected_assumptions reads a seeded outlook
        self.org = Organization.objects.create( name = 'Org' )
        profile  = forecast_profile()
        self.keys = { 'profile': [], 'plans': [], 'assumptions': [] }
        for section in applicable_sections( profile ):
            if section.form is not None:
                self.keys[ flow_of( section ) ].append( section.key )
        record = save_profile( self.org, profile )
        record.acknowledged_sections = self.keys[ 'profile' ]
        record.save()
        self.profile_record = completed_profile( self.org )
        self.scenario = self._runnable_scenario()

    def _runnable_scenario( self ):
        plans_record = PlansRecord(
            organization = self.org, label = 'Foo P', acknowledged_sections = self.keys[ 'plans' ] )
        save_plans( plans_record, Plans() )
        assumptions_record = AssumptionsRecord(
            organization = self.org, label = 'Foo A', acknowledged_sections = self.keys[ 'assumptions' ] )
        save_assumptions( assumptions_record, expected_assumptions() )
        return create_scenario( self.org, plans_record, assumptions_record, 'Foo' )

    def _resume( self ):
        return FinancialForecastView._live_resume(
            scenario_exploration( self.org ), self.profile_record )

    def test_a_clean_exploration_keeps_its_resume( self ):
        enter_exploration( self.org, self.scenario )
        self.assertIsNotNone( self._resume() )

    def test_a_drifted_source_suppresses_the_resume( self ):
        # Explore a clean scenario, then drift its *source* plans (a repayment for a now-missing debt)
        # without touching the working copy: the source the notice names is drift-blocked, so Resume hides.
        enter_exploration( self.org, self.scenario )
        save_plans( self.scenario.plans, Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )
        self.assertIsNone( self._resume() )


class SelectionDefaultsTests( TestCase ):
    """`_selection_defaults`: the hub's first-time duration is the age-based horizon, but a duration the
    user already chose this session always wins -- the computed one never overrides it."""

    def setUp( self ):
        seed_default_parameter_sets()
        self.org = Organization.objects.create( name = 'Org' )
        profile  = forecast_profile()
        keys     = { 'profile': [], 'plans': [], 'assumptions': [] }
        for section in applicable_sections( profile ):
            if section.form is not None:
                keys[ flow_of( section ) ].append( section.key )
        record = save_profile( self.org, profile )
        record.acknowledged_sections = keys[ 'profile' ]
        record.save()
        self.profile_record = completed_profile( self.org )

    @staticmethod
    def _request( **session ):
        state = SimpleNamespace(
            current_scenario_uuid = None, forecast_start_from = None,
            forecast_duration_years = None, forecast_interval = None )
        for key, value in session.items():
            setattr( state, key, value )
        return SimpleNamespace( session_state = state )

    def test_first_time_duration_is_the_age_based_horizon( self ):
        defaults = FinancialForecastView._selection_defaults( self._request(), self.profile_record )
        expected = default_forecast_duration_years(
            load_profile( self.profile_record ), self.profile_record.effective_date )
        self.assertEqual( defaults[ 'duration_years' ], expected )

    def test_a_stored_duration_is_not_overridden( self ):
        request  = self._request( forecast_duration_years = 12 )
        defaults = FinancialForecastView._selection_defaults( request, self.profile_record )
        self.assertEqual( defaults[ 'duration_years' ], 12 )

    def test_without_a_complete_profile_it_falls_back_to_the_floor( self ):
        defaults = FinancialForecastView._selection_defaults( self._request(), None )
        self.assertEqual( defaults[ 'duration_years' ], FORECAST_MIN_YEARS )
