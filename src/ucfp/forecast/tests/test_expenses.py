"""Tests for expense resolution in a Forecast (no DB).

Covers the item-level accounts, the recurrence placement (frequent vs. lumpy), the
lifestyle step via the amount schedule, and the medical-vs-general inflation split.
Expense accounts only receive their own debits, so the assertions are robust to whatever
else posts.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ExpenseItem,
    ForecastParameters,
    Subject,
    WindowedAmount,
)
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile

_MONTHLY = Recurrence( Duration( 1, TimeUnit.MONTH ) )
_YEARLY = Recurrence( Duration( 1, TimeUnit.YEAR ) )
_DECADAL = Recurrence( Duration( 10, TimeUnit.YEAR ) )


def _run():
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.MARRIED_JOINT,
        tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
        subjects      = [ Subject( 'Solo', date( 1960, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
        economic_outlook = EconomicOutlook.constant(
            EconomicParameters( inflation = Rate( Decimal( '0.03' ) ),
                                medical_inflation = Rate( Decimal( '0.05' ) ) ) ),
        expense_items = [
            ExpenseItem( 'Food', ExpenseTaxClass.LIVING,
                         Schedule.constant( WindowedAmount( Decimal( '1000' ) ) ), _MONTHLY,
                         handle = 'food' ),
            ExpenseItem( 'Health Insurance', ExpenseTaxClass.MEDICAL,
                         Schedule.constant( WindowedAmount( Decimal( '12000' ) ) ), _YEARLY,
                         handle = 'health-insurance' ),
            ExpenseItem( 'Car', ExpenseTaxClass.LIVING,
                         Schedule.constant( WindowedAmount( Decimal( '30000' ) ) ), _DECADAL,
                         handle = 'car' ),
            ExpenseItem( 'Travel', ExpenseTaxClass.LIVING, Schedule( (
                WindowedAmount( Decimal( '5000' ), DateWindow( end = date( 2026, 12, 31 ) ) ),
                WindowedAmount( Decimal( '2000' ), DateWindow( start = date( 2027, 1, 1 ) ) ),
            ) ), _YEARLY, handle = 'travel' ),
        ],
    )
    return Forecast( parameters ).run()


def _account( books, handle ):
    return Bookkeeper( books ).chart.account( handle )


def _through( ledger, account, year ):
    return ledger.natural_balance( account, through = date( year, 12, 31 ) )


class ExpenseForecastTests( unittest.TestCase ):

    def test_per_item_accounts_tagged_by_class( self ):
        books = _run().books
        self.assertEqual( _account( books, 'food' ).expense_tax_class, ExpenseTaxClass.LIVING )
        self.assertEqual( _account( books, 'health-insurance' ).expense_tax_class, ExpenseTaxClass.MEDICAL )

    def test_frequent_expense_counts_occurrences( self ):
        books = _run().books
        ledger = Bookkeeper( books ).ledger
        food = _account( books, 'food' )
        # 12 monthly $1000 occurrences, year 1 at today's dollars
        self.assertEqual( _through( ledger, food, 2026 ), Decimal( '12000' ) )
        # + 12 * 1000 * 1.03 in year 2 (general inflation)
        self.assertEqual( _through( ledger, food, 2027 ), Decimal( '24360' ) )

    def test_lumpy_purchase_lands_only_in_its_year( self ):
        books = _run().books
        ledger = Bookkeeper( books ).ledger
        car = _account( books, 'car' )
        # one $30k purchase anchored at the start year, none in the following years
        self.assertEqual( _through( ledger, car, 2026 ), Decimal( '30000' ) )
        self.assertEqual( _through( ledger, car, 2028 ), Decimal( '30000' ) )

    def test_medical_inflates_faster_than_general( self ):
        books = _run().books
        ledger = Bookkeeper( books ).ledger
        health = _account( books, 'health-insurance' )
        # $12k yearly: 12000 in year 1, + 12000 * 1.05 in year 2 (medical inflation)
        self.assertEqual( _through( ledger, health, 2026 ), Decimal( '12000' ) )
        self.assertEqual( _through( ledger, health, 2027 ), Decimal( '24600' ) )

    def test_lifestyle_step_changes_the_amount( self ):
        books = _run().books
        ledger = Bookkeeper( books ).ledger
        travel = _account( books, 'travel' )
        # $5000 in 2026, then $2000 (today's dollars) inflated 3% in 2027
        self.assertEqual( _through( ledger, travel, 2026 ), Decimal( '5000' ) )
        self.assertEqual( _through( ledger, travel, 2027 ), Decimal( '7060' ) )


if __name__ == '__main__':
    unittest.main()
