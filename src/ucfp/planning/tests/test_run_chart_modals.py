"""The run chart modals: `RunChartsModalView` (balances + flows) and
`RunColumnChartModalView` (a books-table column drill-in). Both are read-only, org-scoped
GETs that load a captured run's books and render server-side SVG; the column modal also
resolves an untrusted `?column=` token, which must 404 (never 500) when it names no column.
"""
from django.http import Http404
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.accounts.books_table import BooksColumnKey, BooksDerivedFigure
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile
from ucfp.planning.views import RunChartsModalView, RunColumnChartModalView


class RunChartModalsTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()   # expected_assumptions reads a seeded outlook
        self.org     = Organization.objects.create( name = 'Org' )
        self.profile = load_profile( save_profile( self.org, forecast_profile() ) )
        plans        = save_plans( PlansRecord( organization = self.org, label = 'P' ), Plans() )
        assumptions  = save_assumptions(
            AssumptionsRecord( organization = self.org, label = 'A' ), expected_assumptions() )
        self.scenario = load_scenario( create_scenario( self.org, plans, assumptions, 'S' ) )
        self.run      = run_and_capture(
            organization = self.org, profile = self.profile, plans = self.scenario.plans,
            assumptions = self.scenario.assumptions, frame = forecast_frame(), label = 'S' )
        self.factory  = RequestFactory()

    def _request( self, path, organization = None, **params ):
        request = self.factory.get( path, params, HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.organization = organization or self.org
        return request

    # -- RunChartsModalView (balances + flows) --------------------------------------

    def test_charts_modal_renders_the_charts( self ):
        response = RunChartsModalView().get( self._request( '/charts' ), run_uuid = self.run.uuid )
        self.assertEqual( response.status_code, 200 )
        self.assertIn( 'line-chart', response.content.decode() )

    def test_charts_modal_is_scoped_to_the_org( self ):
        other = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            RunChartsModalView().get(
                self._request( '/charts', organization = other ), run_uuid = self.run.uuid )

    # -- RunColumnChartModalView (per-column drill-in) ------------------------------

    def _net_worth_token( self ):
        return BooksColumnKey.for_derived( BooksDerivedFigure.NET_WORTH ).token

    def test_column_modal_renders_for_a_valid_column( self ):
        response = RunColumnChartModalView().get(
            self._request( '/column-chart', column = self._net_worth_token() ), run_uuid = self.run.uuid )
        self.assertEqual( response.status_code, 200 )
        self.assertIn( 'line-chart', response.content.decode() )

    def test_column_modal_without_a_column_param_is_404( self ):
        with self.assertRaises( Http404 ):
            RunColumnChartModalView().get( self._request( '/column-chart' ), run_uuid = self.run.uuid )

    def test_column_modal_with_an_unknown_token_is_404( self ):
        # An unknown (but well-formed) token names no column -> 404, not a 500.
        with self.assertRaises( Http404 ):
            RunColumnChartModalView().get(
                self._request( '/column-chart', column = 'acct:not-a-real-uuid' ), run_uuid = self.run.uuid )

    def test_column_modal_is_scoped_to_the_org( self ):
        other = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            RunColumnChartModalView().get(
                self._request( '/column-chart', column = self._net_worth_token(), organization = other ),
                run_uuid = self.run.uuid )
