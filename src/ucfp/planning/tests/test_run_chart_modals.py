"""The run chart modals: `RunChartsModalView` (balances + flows) and
`RunColumnChartModalView` (a books-table column drill-in). Both are read-only, org-scoped
GETs that load a captured run's books and render server-side SVG; the column modal also
resolves an untrusted `?column=` token, which must 404 (never 500) when it names no column.
"""
from django.http import Http404
from django.test import RequestFactory, TestCase

from common.dataclass_json import from_json_data
from common.line_chart import CHROME_FULL

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
from ucfp.planning.overview import run_outcome
from ucfp.planning.run_books_cache import load_run_books
from ucfp.planning.run_charts import net_worth_chart
from ucfp.planning.schemas import ProjectionRun
from ucfp.planning.views import RunChartsModalView, RunColumnChartModalView
from ucfp.session_state import SessionState


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
        request.organization  = organization or self.org
        request.session_state = SessionState()   # middleware attaches this on a real request
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

    # -- inflation basis (#263) -----------------------------------------------------

    def _run_and_books( self ):
        return ( from_json_data( ProjectionRun, self.run.data ), load_run_books( self.run.books ) )

    def test_a_chart_deflates_to_todays_dollars_when_adjusted( self ):
        run, books = self._run_and_books()
        nominal  = net_worth_chart( run, books, chrome = CHROME_FULL, adjust_for_inflation = False )
        adjusted = net_worth_chart( run, books, chrome = CHROME_FULL, adjust_for_inflation = True )
        nom, adj = nominal.series[ 0 ].values, adjusted.series[ 0 ].values
        self.assertEqual( adj[ 0 ], nom[ 0 ] )       # opening: nothing to discount in the start year
        self.assertLess( adj[ -1 ], nom[ -1 ] )      # a later year is fewer of today's dollars

    def test_the_adjusted_chart_end_agrees_with_the_summarys_todays_dollars( self ):
        # The chart and the run summary must derive their real-terms figures from the one shared helper, so
        # the chart's ending net worth in today's dollars matches the summary's "Today's $" companion.
        run, books = self._run_and_books()
        today_figure = run_outcome( run, books )[ 'summary' ][ 'end' ][ 'net_worth_today' ]
        self.assertIsNotNone( today_figure )         # solvent, multi-year, inflation set -> a real figure
        chart_end = net_worth_chart(
            run, books, chrome = CHROME_FULL, adjust_for_inflation = True ).series[ 0 ].values[ -1 ]
        self.assertAlmostEqual( chart_end, float( today_figure ), delta = 1.0 )   # agree to the dollar
