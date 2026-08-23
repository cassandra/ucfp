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
from ucfp.planning.books_table import run_period_spans
from ucfp.planning.run_charts import (
    _format_money,
    net_worth_chart,
    run_books_chart,
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
    """A run stand-in exposing only what the adapter reads: yearly result steps."""
    steps = [ SimpleNamespace( start_date = date( year, 1, 1 ), end_date = date( year, 12, 31 ) )
              for year in range( 2026, 2031 ) ]
    return SimpleNamespace( result = SimpleNamespace( stopped_early = False, steps = steps ) )


class RunBooksChartTestCase( unittest.TestCase ):

    def setUp( self ):
        self.run    = _run()
        self.books  = _books()
        self.ledger = Bookkeeper( self.books ).ledger
        self.spans  = run_period_spans( self.run )
        self.chart  = run_books_chart( self.run, self.books )
        self.series = { one.label : one.values for one in self.chart.series }
        return

    def test_series_are_named_in_order( self ):
        self.assertEqual(
            [ one.label for one in self.chart.series ],
            [ 'Net Worth', 'Assets', 'Liabilities', 'Income', 'Expenses' ] )

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
        last            = self.spans[ -1 ]
        period_flow     = float( self.ledger.type_flow(
            AccountType.EXPENSE, start = last.start_date, end = last.end_date ))
        cumulative_total = float( self.ledger.type_total( AccountType.EXPENSE, through = last.end_date ))
        self.assertGreater( cumulative_total, period_flow )
        self.assertEqual( self.series[ 'Expenses' ][ -1 ], period_flow )

    def test_opening_span_has_no_flow( self ):
        self.assertEqual( self.series[ 'Income' ][ 0 ], 0.0 )
        self.assertEqual( self.series[ 'Expenses' ][ 0 ], 0.0 )

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
        self.assertTrue( all( len( tick.label ) == 4 and tick.label.isdigit()
                              for tick in self.chart.x_ticks ) )

    def test_x_ticks_label_forecast_years_not_the_opening_snapshot( self ):
        # The opening span sits at the prior year's close (2025); it is plotted but
        # not ticked, so the axis reads the forecast years (2026 onward).
        labels = [ tick.label for tick in self.chart.x_ticks ]
        self.assertNotIn( '2025', labels )
        self.assertEqual( labels[ 0 ], '2026' )

    def test_series_carry_the_semantic_palette( self ):
        colors = { one.label : one.color for one in self.chart.series }
        self.assertIn( '--chart-net-worth-color', colors[ 'Net Worth' ] )
        self.assertIn( '--chart-expenses-color', colors[ 'Expenses' ] )


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


class FormatMoneyTestCase( unittest.TestCase ):

    def test_compact_currency_labels( self ):
        self.assertEqual( _format_money( 0.0 ), '$0' )
        self.assertEqual( _format_money( -50_000.0 ), '-$50k' )
        self.assertEqual( _format_money( 500_000.0 ), '$500k' )
        self.assertEqual( _format_money( 1_200_000.0 ), '$1.2M' )
        self.assertEqual( _format_money( 750.0 ), '$750' )
