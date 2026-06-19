"""Tests that a Forecast runs at monthly or yearly granularity from the same parameters.

The key properties: flow totals reconcile across granularities (the year's income/expense
is the same whether built in one yearly step or twelve monthly ones), and tax is assessed
only at the year-close interval (December), never monthly.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, Recurrence, TimeUnit
from common.rate import Rate
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ExpenseItem,
    ForecastParameters,
    IncomeStream,
    Subject,
    WindowedAmount,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

_YEARLY = Duration( 1, TimeUnit.YEAR )
_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _parameters( granularity ):
    subject = Subject( 'A', date( 1958, 1, 1 ) )
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.MARRIED_JOINT,
        tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
        granularity   = granularity,
        subjects      = [ subject ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
        economic_outlook = EconomicOutlook.constant(
            EconomicParameters( inflation = Rate( Decimal( '0.03' ) ),
                                social_security_cola = Rate( Decimal( '0.02' ) ) ) ),
        # SS provisional income stays under the taxability threshold, so no tax is charged
        income_streams = [ IncomeStream( subject, IncomeTaxClass.SOCIAL_SECURITY, Decimal( '40000' ) ) ],
        expenses = [
            ExpenseItem( 'Food', ExpenseTaxClass.LIVING,
                         Schedule.constant( WindowedAmount( Decimal( '1000' ) ) ),
                         Recurrence( Duration( 1, TimeUnit.MONTH ) ) ),
        ],
    )


def _balance( books, name ):
    reader = Bookkeeper( books )
    account = next( a for a in reader.chart.accounts() if a.name == name )
    return reader.ledger.natural_balance( account )


class GranularityTests( unittest.TestCase ):

    def test_expense_flows_reconcile_exactly( self ):
        yearly = _balance( Forecast( _parameters( _YEARLY ) ).run().books, 'Food' )
        monthly = _balance( Forecast( _parameters( _MONTHLY ) ).run().books, 'Food' )
        # 12 monthly occurrences per year either way (count_in is span-based), exact
        self.assertEqual( yearly, monthly )

    def test_income_flows_reconcile_to_the_cent( self ):
        yearly = _balance( Forecast( _parameters( _YEARLY ) ).run().books, 'A Social Security' )
        monthly = _balance( Forecast( _parameters( _MONTHLY ) ).run().books, 'A Social Security' )
        # prorated by day-count across months, so equal to the cent (rounding per posting)
        self.assertAlmostEqual( yearly, monthly, places = 2 )

    def test_tax_assessed_only_at_year_close( self ):
        result = Forecast( _parameters( _MONTHLY ) ).run()
        self.assertEqual( len( result.steps ), 36 )
        for step in result.steps:
            is_year_close = ( step.span.end_date.month == 12 ) and ( step.span.end_date.day == 31 )
            if is_year_close:
                self.assertIsNotNone( step.result.closing_tax_state )
            else:
                self.assertIsNone( step.result.closing_tax_state )
            continue


if __name__ == '__main__':
    unittest.main()
