"""Tests for funding draws: covering a cash shortfall from holdings in priority order.

A draw realizes the holding (recognizing any gain into its realized-gain income account,
which the Forecast must have created), refilling cash toward the target.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ExpenseItem,
    ForecastParameters,
    Subject,
    WindowedAmount,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

_LIVING_50K = ExpenseItem(
    'Living', ExpenseTaxClass.LIVING,
    Schedule.constant( WindowedAmount( Decimal( '50000' ) ) ),
    Recurrence( Duration( 1, TimeUnit.YEAR ) ) )


def _parameters( draw_order, outlook = None ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.MARRIED_JOINT,
        tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
        subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
        assets        = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '5000' ) ),
                          AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '500000' ) ) ],
        economic_outlook = outlook if outlook is not None else EconomicOutlook(),
        expenses      = [ _LIVING_50K ],
        cash_target   = Decimal( '10000' ),
        draw_order    = draw_order,
    )


def _account( reader, name ):
    return next( account for account in reader.chart.accounts() if account.name == name )


class FundingDrawTests( unittest.TestCase ):

    def test_no_draw_order_lets_cash_go_negative( self ):
        result = Forecast( _parameters( [] ) ).run()
        reader = Bookkeeper( result.books )
        cash = _account( reader, 'Cash' )
        # $5000 cash - $50000 expense, no source to draw from
        self.assertEqual( reader.ledger.natural_balance( cash ), Decimal( '-45000' ) )

    def test_shortfall_draws_from_priority_class( self ):
        result = Forecast( _parameters( [ AssetClass.STOCKS ] ) ).run()
        reader = Bookkeeper( result.books )
        # drawn back up to the $10000 target; the $55000 shortfall came out of the brokerage
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'Cash' ) ), Decimal( '10000' ) )
        self.assertEqual( reader.ledger.market_value( _account( reader, 'Brokerage' ) ), Decimal( '445000' ) )

    def test_draw_recognizes_the_realized_gain( self ):
        growth = EconomicParameters( stock_appreciation = Rate( Decimal( '0.10' ) ) )
        result = Forecast( _parameters( [ AssetClass.STOCKS ], EconomicOutlook.constant( growth ) ) ).run()
        reader = Bookkeeper( result.books )
        # stock grows 500k -> 550k; drawing 55k (10% of market) realizes 10% of the 50k gain
        gains = next(
            account for account in reader.chart.accounts()
            if account.income_tax_class == IncomeTaxClass.LONG_TERM_GAINS )
        self.assertEqual( reader.ledger.natural_balance( gains ), Decimal( '5000' ) )


if __name__ == '__main__':
    unittest.main()
