"""FinancialForecastView._live_resume: the hub's resume-exploration notice.

It is suppressed when the exploration has drifted against the current profile -- either the `source`
scenario it is anchored to (the one the notice names and the drift block flags) or its `working` copy
references something the profile no longer has. The regression: the check was on the working copy only,
so an exploration of a drift-blocked *source* (whose working copy was a clean older clone) still offered
Resume alongside the block telling the user to reconcile that very scenario.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.exploration import enter_exploration, scenario_exploration
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.state import completed_profile
from ucfp.planning.tests.support import expected_assumptions, forecast_profile
from ucfp.planning.views import FinancialForecastView


class LiveResumeTests( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets', verbosity = 0 )    # expected_assumptions reads a seeded outlook
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
