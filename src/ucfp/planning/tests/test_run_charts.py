"""run_charts: building line-chart specs from a captured run's books.

The adapter reads a run's timeline and per-period figures off the ledger. These
tests run a real (tiny) forecast so the books are genuine, pair it with a minimal
run stand-in (only its result steps are read), and assert each series matches the
ledger primitive it should -- net worth and the asset/liability balances as
end-of-period stocks, income/expenses as within-period flows.
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from common.line_chart import CHROME_FULL, CHROME_SPARKLINE
from common.recurrence import Duration, TimeUnit
from common.rate import Rate

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    LoanParameters,
    Subject,
)
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.accounts.books_table import BooksColumnKey, BooksDerivedFigure
from ucfp.planning.books_table import run_period_spans
from ucfp.planning.run_charts import (
    _child_style,
    _format_money,
    balances_chart,
    column_chart,
    flows_chart,
    net_worth_chart,
)

_D       = Decimal
_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


def _books():
    """A tiny five-year run: cash plus a mortgage, so assets, a liability, and a
    per-period interest expense all move over time."""
    params = ForecastParameters(
        start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
        filing_status = FilingStatus.SINGLE, statute = _STATUTE,
        subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
        assets = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ) ],
        loans = [ LoanParameters(
            name = 'Mortgage', opening_balance = _D( '200000' ),
            interest_rate = Rate.percent( _D( '5' ) ), term = Duration( 30, TimeUnit.YEAR ) ) ],
        economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
    return Forecast( params ).run().books


def _run():
    """A run stand-in exposing what the adapter reads: yearly result steps and the
    profile whose primary subject (born 1960) age-labels the x axis."""
    steps = [ SimpleNamespace( start_date = date( year, 1, 1 ), end_date = date( year, 12, 31 ) )
              for year in range( 2026, 2031 ) ]
    return SimpleNamespace(
        result  = SimpleNamespace( stopped_early = False, steps = steps ),
        profile = SimpleNamespace( subjects = [ SimpleNamespace( birthdate = date( 1960, 1, 1 ) ) ] ) )


class BalancesChartTestCase( unittest.TestCase ):

    def setUp( self ):
        self.run    = _run()
        self.books  = _books()
        self.ledger = Bookkeeper( self.books ).ledger
        self.spans  = run_period_spans( self.run )
        self.chart  = balances_chart( self.run, self.books )
        self.series = { one.label : one.values for one in self.chart.series }
        return

    def test_net_worth_listed_first_so_it_paints_on_top( self ):
        self.assertEqual(
            [ one.label for one in self.chart.series ],
            [ 'Net Worth', 'Assets', 'Liabilities' ] )

    def test_every_series_spans_the_opening_and_each_period( self ):
        # One opening span plus five yearly steps.
        self.assertEqual( len( self.spans ), 6 )
        for values in self.series.values():
            self.assertEqual( len( values ), len( self.spans ) )

    def test_net_worth_matches_the_ledger( self ):
        expected = [ float( self.ledger.net_worth( through = span.end_date )) for span in self.spans ]
        self.assertEqual( self.series[ 'Net Worth' ], expected )

    def test_assets_and_liabilities_are_end_of_period_balances( self ):
        assets = [ float( self.ledger.type_total( AccountType.ASSET, through = span.end_date ))
                   for span in self.spans ]
        liabilities = [ float( self.ledger.type_total( AccountType.LIABILITY, through = span.end_date ))
                        for span in self.spans ]
        self.assertEqual( self.series[ 'Assets' ], assets )
        self.assertEqual( self.series[ 'Liabilities' ], liabilities )

    def test_net_worth_equals_assets_minus_liabilities( self ):
        for net_worth, assets, liabilities in zip(
                self.series[ 'Net Worth' ], self.series[ 'Assets' ], self.series[ 'Liabilities' ] ):
            self.assertAlmostEqual( net_worth, assets - liabilities, places = 6 )

    def test_x_positions_are_monotonic_and_aligned( self ):
        self.assertEqual( len( self.chart.x ), len( self.spans ) )
        self.assertEqual( self.chart.x, sorted( self.chart.x ) )

    def test_full_chrome_carries_axes_and_snapped_domain( self ):
        self.assertEqual( self.chart.chrome, CHROME_FULL )
        self.assertIsNotNone( self.chart.y_min )
        self.assertIsNotNone( self.chart.y_max )
        self.assertTrue( self.chart.y_ticks )
        self.assertTrue( self.chart.x_ticks )
        self.assertTrue( all( tick.label[ :4 ].isdigit() for tick in self.chart.x_ticks ) )

    def test_x_ticks_label_forecast_years_not_the_opening_snapshot( self ):
        # The opening span sits at the prior year's close (2025); it is plotted but
        # not ticked, so the axis reads the forecast years (2026 onward).
        labels = [ tick.label for tick in self.chart.x_ticks ]
        self.assertFalse( any( label.startswith( '2025' ) for label in labels ) )
        self.assertTrue( labels[ 0 ].startswith( '2026' ) )

    def test_x_ticks_carry_the_primary_subject_age( self ):
        # Primary subject born 1960 -> age 66 at end of 2026; shown parenthetically.
        self.assertEqual( self.chart.x_ticks[ 0 ].label, '2026 (66)' )

    def test_series_carry_the_semantic_palette( self ):
        colors = { one.label : one.color for one in self.chart.series }
        self.assertIn( '--chart-net-worth-color', colors[ 'Net Worth' ] )
        self.assertIn( '--chart-liabilities-color', colors[ 'Liabilities' ] )


class FlowsChartTestCase( unittest.TestCase ):

    def setUp( self ):
        self.run    = _run()
        self.books  = _books()
        self.ledger = Bookkeeper( self.books ).ledger
        self.spans  = run_period_spans( self.run )
        self.chart  = flows_chart( self.run, self.books )
        self.series = { one.label : one.values for one in self.chart.series }
        return

    def test_series_are_income_then_expenses( self ):
        self.assertEqual( [ one.label for one in self.chart.series ], [ 'Income', 'Expenses' ] )

    def test_income_and_expenses_are_within_period_flows( self ):
        expenses = [ float( self.ledger.type_flow(
            AccountType.EXPENSE, start = span.start_date, end = span.end_date )) for span in self.spans ]
        income = [ float( self.ledger.type_flow(
            AccountType.REVENUE, start = span.start_date, end = span.end_date )) for span in self.spans ]
        self.assertEqual( self.series[ 'Expenses' ], expenses )
        self.assertEqual( self.series[ 'Income' ], income )

    def test_expenses_use_period_flow_not_cumulative_total( self ):
        # The mortgage books interest every period, so the cumulative expense total
        # at the final period exceeds that single period's flow -- confirming the
        # series is the flow, not the running total.
        last             = self.spans[ -1 ]
        period_flow      = float( self.ledger.type_flow(
            AccountType.EXPENSE, start = last.start_date, end = last.end_date ))
        cumulative_total = float( self.ledger.type_total( AccountType.EXPENSE, through = last.end_date ))
        self.assertGreater( cumulative_total, period_flow )
        self.assertEqual( self.series[ 'Expenses' ][ -1 ], period_flow )

    def test_opening_span_has_no_flow( self ):
        self.assertEqual( self.series[ 'Income' ][ 0 ], 0.0 )
        self.assertEqual( self.series[ 'Expenses' ][ 0 ], 0.0 )


class NetWorthChartTestCase( unittest.TestCase ):

    def setUp( self ):
        self.run    = _run()
        self.books  = _books()
        self.ledger = Bookkeeper( self.books ).ledger
        self.spans  = run_period_spans( self.run )
        return

    def test_defaults_to_a_single_series_sparkline( self ):
        chart = net_worth_chart( self.run, self.books )
        self.assertEqual( chart.chrome, CHROME_SPARKLINE )
        self.assertEqual( len( chart.series ), 1 )
        self.assertEqual( chart.series[ 0 ].label, 'Net Worth' )
        # A sparkline carries no ticks.
        self.assertIsNone( chart.x_ticks )
        self.assertIsNone( chart.y_ticks )
        # It scales to the data (fills its box) rather than forcing a zero baseline.
        self.assertFalse( chart.include_zero )

    def test_values_match_the_ledger_net_worth( self ):
        chart    = net_worth_chart( self.run, self.books )
        expected = [ float( self.ledger.net_worth( through = span.end_date )) for span in self.spans ]
        self.assertEqual( chart.series[ 0 ].values, expected )

    def test_can_render_full_chrome_on_request( self ):
        chart = net_worth_chart( self.run, self.books, chrome = CHROME_FULL )
        self.assertEqual( chart.chrome, CHROME_FULL )
        self.assertTrue( chart.y_ticks )


def _column_books():
    """Books with several asset accounts -- Cash and Stocks funded, Bonds at zero -- plus a
    mortgage, so an Asset drill-in has two non-zero children and a zero child to skip, while
    the Liability rollup has a single child (the mortgage)."""
    params = ForecastParameters(
        start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
        filing_status = FilingStatus.SINGLE, statute = _STATUTE,
        subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ),
            AssetParameters( 'Stocks', AssetClass.STOCKS, _D( '100000' ), _D( '100000' ) ),
            AssetParameters( 'Bonds', AssetClass.BONDS, _D( '0' ), _D( '0' ) ) ],
        loans = [ LoanParameters(
            name = 'Mortgage', opening_balance = _D( '200000' ),
            interest_rate = Rate.percent( _D( '5' ) ), term = Duration( 30, TimeUnit.YEAR ) ) ],
        economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
    return Forecast( params ).run().books


class ColumnChartTestCase( unittest.TestCase ):

    def setUp( self ):
        self.run   = _run()
        self.books = _column_books()
        return

    def test_leaf_column_is_a_single_total_line( self ):
        key   = BooksColumnKey.for_derived( BooksDerivedFigure.NET_WORTH )
        chart = column_chart( self.run, self.books, key )
        self.assertEqual( len( chart.series ), 1 )
        self.assertIn( '--chart-total-color', chart.series[ 0 ].color )
        self.assertIsNone( chart.series[ 0 ].dash )

    def test_summary_lists_rollup_first_then_children( self ):
        chart = column_chart( self.run, self.books, BooksColumnKey.for_type( AccountType.ASSET ) )
        # Rollup (dark total, painted on top) plus its two non-zero children in categorical hues.
        self.assertEqual( len( chart.series ), 3 )
        self.assertIn( '--chart-total-color', chart.series[ 0 ].color )
        self.assertIn( '--chart-cat-1', chart.series[ 1 ].color )

    def test_zero_children_are_dropped( self ):
        chart  = column_chart( self.run, self.books, BooksColumnKey.for_type( AccountType.ASSET ) )
        labels = [ one.label for one in chart.series ]
        # Bonds hold zero throughout, so they are not drawn.
        self.assertNotIn( 'Bonds', labels )

    def test_single_child_rollup_collapses_to_one_line( self ):
        # The Liability rollup has just the mortgage, so its line equals that child's:
        # one line, named for both.
        chart = column_chart( self.run, self.books, BooksColumnKey.for_type( AccountType.LIABILITY ) )
        self.assertEqual( len( chart.series ), 1 )
        self.assertIn( '>', chart.series[ 0 ].label )
        self.assertIn( 'Mortgage', chart.series[ 0 ].label )

    def test_unknown_column_raises( self ):
        with self.assertRaises( ValueError ):
            column_chart( self.run, self.books, BooksColumnKey.for_account(
                UUID( '00000000-0000-0000-0000-000000000000' ) ) )


class ChildStyleTestCase( unittest.TestCase ):

    def test_categorical_hues_solid_then_dashed( self ):
        # The first five children are solid categorical hues; the sixth and seventh
        # repeat the hues dashed (the second channel).
        self.assertEqual( _child_style( 0 ), ( 'var(--chart-cat-1, #2a78d6)', None ) )
        self.assertEqual( _child_style( 4 )[ 1 ], None )
        self.assertEqual( _child_style( 5 ), ( 'var(--chart-cat-1, #2a78d6)', '6 4' ) )
        self.assertEqual( _child_style( 6 ), ( 'var(--chart-cat-2, #008300)', '6 4' ) )


class FormatMoneyTestCase( unittest.TestCase ):

    def test_compact_currency_labels( self ):
        self.assertEqual( _format_money( 0.0 ), '$0' )
        self.assertEqual( _format_money( -50_000.0 ), '-$50k' )
        self.assertEqual( _format_money( 500_000.0 ), '$500k' )
        self.assertEqual( _format_money( 1_200_000.0 ), '$1.2M' )
        self.assertEqual( _format_money( 750.0 ), '$750' )
