"""Income tax as a payable settled the following year (#170).

Tax assessed for a year is accrued to a Taxes Payable liability at that year's close -- owed but
not yet paid -- and settled to cash on the tax law's payment date (April 15) the following year.
This decouples the payment from the assessment: the draw that funds the payment falls in the next
year and is taxed there, breaking the within-year draw<->tax loop, and net worth reflects the tax
owed the moment it is assessed.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import (
    AccountType, AssetClass, ExpenseTaxClass, IncomeTaxClass, SystemAccountRole )
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, IncomeStream, Subject, WindowedAmount )
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from common.schedule import Schedule

_D       = Decimal
_US      = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_PAYABLE = SystemAccountRole.TAXES_PAYABLE


def _run_wage_forecast():
    """A single earner on 100k wages, 50k cash, 2026-2028 -- a steady income-tax liability (deferred to
    the payable) and FICA (withheld in-year) each year, with cash ample enough that no shortfall
    funding muddies the picture."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _US,
        subjects      = [ worker ],
        assets        = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '50000' ), _D( '50000' ) ) ],
        income_streams = [ IncomeStream(
            worker, IncomeTaxClass.WAGES, Schedule.constant( WindowedAmount( _D( '100000' ) ) ) ) ],
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _deferred_tax_expense( reader, year ):
    """The tax expense that defers to the payable in `year` -- the income-tax layers, NIIT, state, and
    the early-withdrawal penalty. Excludes FICA, which is withheld in-year rather than deferred."""
    start, end = date( year, 1, 1 ), date( year, 12, 31 )
    total = _D( '0' )
    for account in reader.chart.accounts( account_type = AccountType.EXPENSE ):
        tax_class = account.expense_tax_class
        if ( tax_class is not None and tax_class.is_tax_payment
                and tax_class is not ExpenseTaxClass.EMPLOYMENT_TAX ):
            total += reader.ledger.natural_flow( account, start = start, end = end )
    return total


class TaxPayableTests( unittest.TestCase ):

    def test_income_tax_is_accrued_to_the_payable_at_year_close_not_paid_from_cash( self ):
        reader = _run_wage_forecast()
        payable = reader.chart.system_account( _PAYABLE )
        owed = reader.ledger.natural_balance( payable, through = date( 2026, 12, 31 ) )
        # 2026's deferred tax (income tax + penalties, not FICA) stands as a liability at year end.
        self.assertGreater( owed, _D( '0' ) )
        self.assertEqual( owed, _deferred_tax_expense( reader, 2026 ) )

    def test_employment_tax_is_withheld_in_year_not_deferred( self ):
        reader = _run_wage_forecast()
        fica = reader.chart.expense_account( ExpenseTaxClass.EMPLOYMENT_TAX )
        payable = reader.chart.system_account( _PAYABLE )
        # FICA is booked as a 2026 expense (withheld that year) ...
        self.assertGreater(
            reader.ledger.natural_flow( fica, start = date( 2026, 1, 1 ), end = date( 2026, 12, 31 ) ),
            _D( '0' ) )
        # ... and stays out of the deferred payable, which is exactly the non-FICA tax.
        owed = reader.ledger.natural_balance( payable, through = date( 2026, 12, 31 ) )
        self.assertEqual( owed, _deferred_tax_expense( reader, 2026 ) )
        # The withholding lands in-year as its own transaction.
        withholdings = [ txn for txn in reader.books.transactions
                         if txn.description == 'FICA withholding' and txn.transaction_date.year == 2026 ]
        self.assertTrue( withholdings )

    def test_year_end_net_worth_reflects_the_tax_owed( self ):
        reader = _run_wage_forecast()
        payable = reader.chart.system_account( _PAYABLE )
        owed = reader.ledger.natural_balance( payable, through = date( 2026, 12, 31 ) )
        # No debts in this profile, so the payable is the whole liability side that net worth nets out.
        self.assertEqual(
            reader.ledger.type_total( AccountType.LIABILITY, through = date( 2026, 12, 31 ) ), owed )

    def test_the_payable_is_settled_to_cash_the_following_april( self ):
        reader = _run_wage_forecast()
        payable = reader.chart.system_account( _PAYABLE )
        cash = reader.chart.cash_account()
        owed_2026 = reader.ledger.natural_balance( payable, through = date( 2026, 12, 31 ) )

        settlements = [ txn for txn in reader.books.transactions
                        if txn.description == 'Prior-year tax settlement'
                        and txn.transaction_date == date( 2027, 4, 15 ) ]
        self.assertEqual( len( settlements ), 1 )   # 2026's tax settled once, on the 2027 payment date

        settlement = settlements[ 0 ]
        payable_entry = next( e for e in settlement.entries if e.account is payable )
        cash_entry    = next( e for e in settlement.entries if e.account is cash )
        self.assertEqual( payable_entry.signed_amount, -owed_2026 )   # DR the liability down to zero
        self.assertEqual( cash_entry.signed_amount, owed_2026 )       # CR cash by the same

    def test_each_year_carries_only_its_own_tax_to_the_next( self ):
        # By the time 2027's payment date has passed, the payable holds nothing from 2026: the year's
        # accrual and the next year's settlement cycle cleanly, so no tax is ever carried twice.
        reader = _run_wage_forecast()
        payable = reader.chart.system_account( _PAYABLE )
        # Just after the 2027 settlement but before 2027's own year-close accrual, the payable is clear.
        self.assertEqual(
            reader.ledger.natural_balance( payable, through = date( 2027, 4, 15 ) ), _D( '0' ) )


if __name__ == '__main__':
    unittest.main()
