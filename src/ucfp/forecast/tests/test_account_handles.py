"""Tests that handles reach every account the Forecast creates from a planner input.

The planning layer mints a handle per input artifact and, to associate its artifacts with
the resulting books, expects each input-created account to carry it: a loan's liability and
its interest expense (two handles, one per account), and an expense item's account. Income
accounts are shared per (subject, class), so they carry the subject's handle as `owner_handle`
rather than an own handle. Derived per-class and system accounts carry none.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, SystemAccountRole
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ExpenseItem,
    ForecastParameters,
    IncomeStream,
    LoanParameters,
    Subject,
    WindowedAmount,
)
from ucfp.tax.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile


def _account( reader, name ):
    return next( account for account in reader.chart.accounts() if account.name == name )


class AccountHandleTests( unittest.TestCase ):

    def _reader( self ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.ORDINARY,
                              Schedule.constant( WindowedAmount( Decimal( '30000' ) ) ) ) ],
            expense_items = [
                ExpenseItem(
                    'Groceries', ExpenseTaxClass.LIVING,
                    Schedule.constant( WindowedAmount( Decimal( '500' ) ) ),
                    Recurrence( Duration( 1, TimeUnit.MONTH ) ),
                    handle = 'groceries' ) ],
            loans         = [
                LoanParameters(
                    'Mortgage', Decimal( '200000' ), Rate( Decimal( '0.05' ) ),
                    Duration( 30, TimeUnit.YEAR ), ExpenseTaxClass.MORTGAGE_INTEREST,
                    handle = 'mortgage', interest_handle = 'mortgage-interest' ) ],
        )
        return Bookkeeper( Forecast( parameters ).run().books )

    def test_loan_accounts_carry_their_two_handles( self ):
        reader = self._reader()
        self.assertEqual( str( _account( reader, 'Mortgage' ).handle ), 'mortgage' )
        self.assertEqual( str( _account( reader, 'Mortgage Interest' ).handle ), 'mortgage-interest' )

    def test_expense_account_carries_its_handle( self ):
        reader = self._reader()
        self.assertEqual( str( _account( reader, 'Groceries' ).handle ), 'groceries' )

    def test_income_account_carries_its_owner_handle( self ):
        reader = self._reader()
        income = _account( reader, 'A Ordinary Income' )
        self.assertEqual( str( income.owner_handle ), 'subject-a' )
        self.assertIsNone( income.handle )

    def test_system_account_carries_no_handle( self ):
        reader = self._reader()
        opening = reader.chart.system_account( SystemAccountRole.OPENING_BALANCES )
        self.assertIsNone( opening.handle )

    def test_chart_account_accessor_finds_by_handle( self ):
        # the query surface: the planner reaches its resulting account by the handle it minted
        reader = self._reader()
        self.assertIs( reader.chart.account( 'mortgage' ), _account( reader, 'Mortgage' ) )
        self.assertIs(
            reader.chart.account( 'mortgage-interest' ), _account( reader, 'Mortgage Interest' ) )
        self.assertIsNone( reader.chart.account( 'no-such-handle' ) )


if __name__ == '__main__':
    unittest.main()
