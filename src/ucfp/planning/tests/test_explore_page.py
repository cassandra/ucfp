"""The Explore workspace renders its Inputs → Re-run → Output layout: the Re-run CTA and the outcome banner
(did the money last, the ending net worth, the horizon) appear with the selected run, so the run is visible
rather than buried below the inputs. A full render also guards the template against context/filter drift --
the `money` filter, the `run_outcome` figures, and the `currency` context processor.
"""
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.exploration import enter_exploration
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.state import input_state
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.session_state import SessionState
from ucfp.planning.views import ExploreView

from .support import expected_assumptions, forecast_profile


class ExplorePageRenderTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.organization = Organization.objects.create( name = 'Org' )
        save_profile( self.organization, forecast_profile() )
        plans = save_plans( PlansRecord( organization = self.organization, label = 'P' ), Plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'A' ), expected_assumptions() )
        self.scenario = create_scenario( self.organization, plans, assumptions, 'Base' )
        enter_exploration( self.organization, self.scenario )

    def _get( self ):
        request = RequestFactory().get( '/plan/financial-forecast/explore/' )
        request.user          = AnonymousUser()
        request.organization  = self.organization
        request.input_state   = input_state( self.organization )
        request.session_state = SessionState()
        request.session       = {}
        return ExploreView().get( request )

    def test_page_renders_rerun_cta_and_outcome_banner( self ):
        response = self._get()
        self.assertEqual( response.status_code, 200 )
        body = response.content.decode()
        self.assertIn( 'Re-run', body )                             # the inputs-foot CTA
        self.assertIn( 'run-summary', body )                        # the shared outcome summary rendered
        self.assertIn( 'Start', body )                             # the start→end arc from the shared summary

    def test_page_renders_the_balances_thumbnail( self ):
        # Charts are as useful while exploring as on a saved run, so the summary's
        # clickable balances thumbnail renders here too.
        body = self._get().content.decode()
        self.assertIn( 'run-summary-chart__svg', body )
        self.assertIn( '<polyline', body )
