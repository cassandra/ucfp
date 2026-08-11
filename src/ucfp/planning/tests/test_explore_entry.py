"""EnterExploreView's entry behavior: resume-vs-reseed idempotency and frame capture. Re-entering the
scenario already in progress resumes it (its tweaks and transient runs intact), while entering a
*different* scenario re-seeds the sandbox from the new anchor and clears the runs -- guarding intact user
work across a page refresh or a re-click (a regression that dropped the `source_id` guard would silently
discard tweaks and run history). Entry also records the chosen projection frame onto the exploration, so
the workspace projects over it rather than a session default -- the fix for the initial run silently using
a mid-year start (an untaxed partial first year) when the user chose start-of-year.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.http import QueryDict
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.scenarios.exploration import overwrite_working, scenario_exploration, working_scenario
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.session_state import SessionState
from ucfp.planning.explore import run_working_scenario, transient_runs
from ucfp.planning.views import EnterExploreView, ExploreView

from .support import expected_assumptions, forecast_frame, forecast_profile


def _tweaked_plans() -> Plans:
    """A Plans distinct from the anchors' empty `Plans()`, so a surviving tweak is detectable."""
    return Plans( drawdown = DrawdownPolicy(
        cash_floor = Decimal( '25000' ), cash_ceiling = Decimal( '50000' ) ) )


class EnterExploreIdempotencyTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )
        save_profile( self.organization, forecast_profile() )
        self.one = self._saved( 'One' )
        self.two = self._saved( 'Two' )
        self.factory = RequestFactory()

    def _saved( self, label ):
        plans       = save_plans( PlansRecord( organization = self.organization, label = f'{label} plans' ),
                                  Plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = f'{label} assumptions' ),
            expected_assumptions() )
        return create_scenario( self.organization, plans, assumptions, label )

    def _enter( self, scenario, start_from = 'effective', duration_years = '40', interval = 'year' ):
        """Drive EnterExploreView.post as the hub does -- the scenario and frame in the posted form."""
        data = QueryDict( mutable = True )
        data.update( { 'scenario': str( scenario.uuid ), 'start_from': start_from,
                       'duration_years': duration_years, 'interval': interval } )
        request = self.factory.post( '/enter', data )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = {}
        return EnterExploreView().post( request )

    def test_reentering_the_same_scenario_resumes_keeping_tweaks_and_runs( self ):
        self._enter( self.one )
        run_working_scenario( self.organization, forecast_frame() )
        tweaked = Scenario( plans = _tweaked_plans(), assumptions = expected_assumptions() )
        overwrite_working( self.organization, tweaked )
        self.assertEqual( transient_runs( self.organization ).count(), 1 )

        self._enter( self.one )                                       # re-enter the SAME anchor

        self.assertEqual( load_scenario( working_scenario( self.organization ) ), tweaked )   # tweak survived
        self.assertEqual( transient_runs( self.organization ).count(), 1 )                    # runs intact
        self.assertEqual( scenario_exploration( self.organization ).source_id, self.one.id )

    def test_entering_a_different_scenario_reseeds_and_clears_runs( self ):
        self._enter( self.one )
        run_working_scenario( self.organization, forecast_frame() )
        overwrite_working( self.organization, Scenario() )            # tweak the sandbox away from the anchor
        self.assertEqual( transient_runs( self.organization ).count(), 1 )

        self._enter( self.two )                                      # switch to a different anchor

        self.assertEqual( scenario_exploration( self.organization ).source_id, self.two.id )
        self.assertEqual(                                            # re-seeded from the new anchor...
            load_scenario( working_scenario( self.organization ) ), load_scenario( self.two ) )
        self.assertEqual( transient_runs( self.organization ).count(), 0 )   # ...and the runs cleared

    def test_entry_records_the_chosen_frame_on_the_exploration( self ):
        self._enter( self.one, start_from = 'this_year', duration_years = '30', interval = 'quarter' )
        exploration = scenario_exploration( self.organization )
        self.assertEqual( exploration.frame_start_from, 'this_year' )
        self.assertEqual( exploration.frame_duration_years, 30 )
        self.assertEqual( exploration.frame_interval, 'quarter' )

    def test_the_run_frame_comes_from_the_exploration_not_the_session( self ):
        # The reported bug: the initial run took the session's default start (mid-year effective) instead of
        # the chosen start-of-year, which made the first year partial and dropped its taxes. The run frame
        # now derives from the frame recorded on the exploration, so a stale/blank session value cannot
        # override the entered choice -- a start-of-year entry stays a January-1 (full, taxed) first year.
        self._enter( self.one, start_from = 'this_year' )
        request = self.factory.get( '/explore' )
        request.organization  = self.organization
        request.session_state = SessionState( forecast_start_from = 'effective' )   # the wrong default
        frame     = ExploreView()._frame( request )
        effective = latest_profile( self.organization ).effective_date
        self.assertEqual( frame.start_date, date( effective.year, 1, 1 ) )          # Jan 1, from exploration
