"""Explore workspace under Profile drift: when the exploration's runs were computed against an earlier
Profile than the current one, new runs pause (Re-run and the auto-run on the workspace), the changed facts
surface, and the runs stay viewable -- until the user re-baselines on the current Profile.
"""
from dataclasses import replace

from django.core.management import call_command
from django.http import QueryDict
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.state import input_state
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.session_state import SessionState
from ucfp.planning.explore import run_working_scenario, transient_runs
from ucfp.planning.views import EnterExploreView, ExploreRestartView, ExploreView

from .support import expected_assumptions, forecast_frame, forecast_profile


class ExploreProfileDriftTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )
        save_profile( self.organization, forecast_profile() )        # the Profile the baseline run will embed
        self.scenario = self._saved_scenario()
        self.factory  = RequestFactory()
        self._enter( self.scenario )
        run_working_scenario( self.organization, forecast_frame() )  # a baseline run against the current Profile

    def _saved_scenario( self ):
        plans = save_plans( PlansRecord( organization = self.organization, label = 'plans' ), Plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'assumptions' ), expected_assumptions() )
        return create_scenario( self.organization, plans, assumptions, 'Scenario' )

    def _enter( self, scenario ):
        data = QueryDict( mutable = True )
        data.update( { 'scenario': str( scenario.uuid ), 'start_from': 'effective',
                       'duration_years': '40', 'interval': 'year' } )
        EnterExploreView().post( self._request( self.factory.post( '/enter', data ) ) )

    def _request( self, request ):
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = {}
        request.input_state   = input_state( self.organization )
        return request

    def _change_the_profile( self ):
        # Save a Profile with a changed fact, so it differs from the one the baseline run embedded.
        save_profile( self.organization, replace( forecast_profile(), filing_status = FilingStatus.MARRIED_JOINT ) )

    def _runs( self ) -> int:
        return transient_runs( self.organization ).count()

    def _drift( self ) -> list:
        return ExploreView()._profile_drift( self.organization, list( transient_runs( self.organization ) ) )

    # -- detection ----------------------------------------------------------

    def test_no_drift_before_the_profile_changes( self ):
        self.assertEqual( self._drift(), [] )

    def test_a_profile_change_is_detected_and_described( self ):
        self._change_the_profile()
        self.assertEqual( self._drift(), [ 'Filing status Single → Married Filing Jointly' ] )

    # -- pausing new runs ---------------------------------------------------

    def test_rerun_is_blocked_while_drifted( self ):
        self._change_the_profile()
        before = self._runs()
        ExploreView().post( self._request( self.factory.post( '/explore' ) ) )   # Re-run
        self.assertEqual( self._runs(), before )                                 # no new run piled on

    def test_the_workspace_shows_the_banner_and_hides_the_inputs( self ):
        self._change_the_profile()
        response = ExploreView().get( self._request( self.factory.get( '/explore' ) ) )
        self.assertEqual( self._runs(), 1 )                                      # did not auto-run
        self.assertIn( b'Your Profile has changed', response.content )
        self.assertIn( b'Filing status Single', response.content )
        self.assertNotIn( b'Re-run the forecast', response.content )             # input area replaced

    def test_rerun_still_works_without_drift( self ):
        before = self._runs()
        ExploreView().post( self._request( self.factory.post( '/explore' ) ) )
        self.assertGreater( self._runs(), before )

    # -- re-baselining ------------------------------------------------------

    def test_restart_rebaselines_on_the_current_profile( self ):
        self._change_the_profile()
        ExploreRestartView().post( self._request( self.factory.post( '/restart' ) ) )
        self.assertEqual( self._runs(), 0 )     # runs cleared; the workspace re-runs lazily on the new Profile
        run_working_scenario( self.organization, forecast_frame() )
        self.assertEqual( self._drift(), [] )   # the new baseline run is on the current Profile -- no drift
