"""Income tax as a payable, prepaid in-year as a safe-harbor estimate and trued up the next year (#170).

Income tax is prepaid through the year as a capped estimate -- the lesser of the prior year's tax and
this year's liability so far -- so most of it leaves cash in-year. The year-end settlement books the
full true tax as expense and nets the prepayment against the Taxes Payable liability, leaving only the
balance (this year's growth, one-time spikes, and funding-draw gains) owed, and paid the following
April. FICA is withheld separately in-year (#170 phase 3a), so it never sits on the payable.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import Rate
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import (
    AccountType, AssetClass, ExpenseTaxClass, IncomeTaxClass, SystemAccountRole )
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, CashAccountParameters, ExpenseStream, ForecastParameters, IncomeStream,
    Subject, WindowedAmount )
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.engine import ZeroTaxEngine
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.period.parameters import AssetRates, FundingPolicy, PeriodParameters
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult
from common.date_span import DateSpan

_D          = Decimal
_US         = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_PAYABLE    = SystemAccountRole.TAXES_PAYABLE
_INCOME_TAX = ( ExpenseTaxClass.ORDINARY_INCOME_TAX, ExpenseTaxClass.CAPITAL_GAINS_TAX,
                ExpenseTaxClass.SECTION_1250_TAX, ExpenseTaxClass.COLLECTIBLES_TAX,
                ExpenseTaxClass.NIIT, ExpenseTaxClass.STATE_INCOME_TAX )
_CONSTANT   = Schedule.constant( WindowedAmount( _D( '100000' ) ) )


def _run( wages, end_year = 2028, wage_growth = '0' ):
    """A single earner on `wages`, ample cash (so no funding draw or sweep muddies the tax), over
    2026..end_year. `wage_growth` nominally grows the stream, which makes this year's tax outrun the
    prior-year cap and leaves a true-up on the payable."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( end_year, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _US,
        subjects      = [ worker ],
        assets        = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '200000' ), _D( '200000' ) ) ],
        economic_outlook = EconomicOutlook.constant(
            EconomicParameters( wage_growth = Rate( _D( wage_growth ) ) ) ),
        income_streams = [ IncomeStream( worker, IncomeTaxClass.WAGES, wages ) ],
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _run_drawdown():
    """A solvent household whose spending plus tax outruns its wages, so it draws from stocks against a
    cash floor every year -- the tight-cash regime where a year-end tax lump would have punched Cash &
    Savings below the floor (the #170 negative-savings bug) before tax moved in-year."""
    worker = Subject( 'Worker', date( 1970, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2030, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _US,
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '30000' ), _D( '30000' ) ),
            AssetParameters( 'Stocks', AssetClass.STOCKS, _D( '300000' ), _D( '300000' ) ) ],
        income_streams  = [ IncomeStream(
            worker, IncomeTaxClass.WAGES, Schedule.constant( WindowedAmount( _D( '100000' ) ) ) ) ],
        expense_streams = [ ExpenseStream(
            'Living', ExpenseTaxClass.LIVING, Schedule.constant( WindowedAmount( _D( '110000' ) ) ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = _D( '25000' ), draw_order = [ AssetClass.STOCKS ] ),
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _run_gainful_drawdown():
    """Like `_run_drawdown`, but the drawn stocks carry an embedded gain (basis below value), so each
    funding draw realizes a capital gain -- income the pre-draw estimate cannot see but the year-end
    settlement does."""
    worker = Subject( 'Worker', date( 1970, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2030, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _US,
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '30000' ), _D( '30000' ) ),
            AssetParameters( 'Stocks', AssetClass.STOCKS, _D( '300000' ), _D( '100000' ) ) ],
        income_streams  = [ IncomeStream(
            worker, IncomeTaxClass.WAGES, Schedule.constant( WindowedAmount( _D( '100000' ) ) ) ) ],
        expense_streams = [ ExpenseStream(
            'Living', ExpenseTaxClass.LIVING, Schedule.constant( WindowedAmount( _D( '110000' ) ) ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = _D( '25000' ), draw_order = [ AssetClass.STOCKS ] ),
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _run_retirement_drawdown():
    """A young household (owner under 59.5) with no wages, spending from a pre-tax retirement account it
    must draw early -- so every draw incurs the 10% early-withdrawal penalty."""
    worker = Subject( 'Worker', date( 1990, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _US,
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '30000' ), _D( '30000' ) ),
            AssetParameters( 'Pre-Tax Retirement', AssetClass.PRETAX_RETIREMENT, _D( '300000' ), _D( '0' ),
                             owner_handle = 'worker' ) ],
        expense_streams = [ ExpenseStream(
            'Living', ExpenseTaxClass.LIVING, Schedule.constant( WindowedAmount( _D( '50000' ) ) ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = _D( '25000' ), draw_order = [ AssetClass.PRETAX_RETIREMENT ] ),
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _income_tax_expense( reader, year ):
    """The full true income tax booked to the rate-layer expense accounts in `year` (accrual, at the
    year-end settlement) -- independent of what was prepaid."""
    start, end = date( year, 1, 1 ), date( year, 12, 31 )
    total = _D( '0' )
    for tax_class in _INCOME_TAX:
        account = reader.chart.expense_account( tax_class )
        if account is not None:
            total += reader.ledger.natural_flow( account, start = start, end = end )
    return total


def _cash_out( reader, description, year ):
    """Cash leaving on the transactions memoed `description` in `year` (a positive outflow -- the cash
    account is debit-normal, so a credit reducing it carries a positive credit-signed amount)."""
    cash = reader.chart.cash_account()
    total = _D( '0' )
    for txn in reader.books.transactions:
        if txn.description == description and txn.transaction_date.year == year:
            total += sum( ( entry.signed_amount for entry in txn.entries if entry.account is cash ), _D( '0' ) )
    return total


class IncomeTaxEstimateTests( unittest.TestCase ):

    def test_income_tax_is_prepaid_in_year( self ):
        reader = _run( _CONSTANT )
        # Income tax leaves cash mid-year as an estimate, rather than the whole bill floating to April.
        self.assertGreater( _cash_out( reader, 'Estimated income tax (prepayment)', 2026 ), _D( '0' ) )

    def test_expense_carries_the_full_true_tax_though_prepaid( self ):
        reader = _run( _CONSTANT )
        # The prepayment touches no expense account; the year-end settlement books the whole true tax,
        # so the rate-layer expense accounts still show the full year's income tax.
        self.assertGreater( _income_tax_expense( reader, 2026 ), _D( '0' ) )

    def test_a_steady_earner_owes_nothing_at_year_end( self ):
        reader = _run( _CONSTANT )
        payable = reader.chart.system_account( _PAYABLE )
        # Flat income and no draws: the estimate equals the true tax, so nothing is left on the payable.
        self.assertEqual( reader.ledger.natural_balance( payable, through = date( 2026, 12, 31 ) ), _D( '0' ) )

    def test_growth_defers_only_the_increase_to_the_payable( self ):
        reader = _run( _CONSTANT, wage_growth = '0.05' )
        payable = reader.chart.system_account( _PAYABLE )
        owed     = reader.ledger.natural_balance( payable, through = date( 2027, 12, 31 ) )
        prepaid  = _cash_out( reader, 'Estimated income tax (prepayment)', 2027 )
        true_tax = _income_tax_expense( reader, 2027 )
        self.assertGreater( owed, _D( '0' ) )     # the cap holds the estimate at last year's tax ...
        self.assertLess( owed, true_tax )         # ... so only the year-over-year increase is owed
        self.assertEqual( prepaid + owed, true_tax )   # prepayment + balance == the full true tax

    def test_year_end_net_worth_reflects_the_payable( self ):
        reader = _run( _CONSTANT, wage_growth = '0.05' )
        payable = reader.chart.system_account( _PAYABLE )
        owed = reader.ledger.natural_balance( payable, through = date( 2027, 12, 31 ) )
        # No debts, so the payable is the whole liability side that net worth nets out.
        self.assertEqual(
            reader.ledger.type_total( AccountType.LIABILITY, through = date( 2027, 12, 31 ) ), owed )

    def test_the_balance_is_settled_to_cash_the_following_april( self ):
        reader = _run( _CONSTANT, wage_growth = '0.05' )
        payable = reader.chart.system_account( _PAYABLE )
        owed_2027 = reader.ledger.natural_balance( payable, through = date( 2027, 12, 31 ) )
        settlements = [ txn for txn in reader.books.transactions
                        if txn.description == 'Prior-year tax settlement'
                        and txn.transaction_date == date( 2028, 4, 15 ) ]
        self.assertEqual( len( settlements ), 1 )
        self.assertEqual( _cash_out( reader, 'Prior-year tax settlement', 2028 ), owed_2027 )

    def test_a_spike_year_floats_past_the_cap_without_overcharging_the_next( self ):
        # A one-time bonus in 2028 spikes that year's tax; 2027 and 2029 are ordinary.
        bonus = Schedule( (
            WindowedAmount( _D( '100000' ), DateWindow( end = date( 2027, 12, 31 ) ) ),
            WindowedAmount( _D( '300000' ),
                            DateWindow( start = date( 2028, 1, 1 ), end = date( 2028, 12, 31 ) ) ),
            WindowedAmount( _D( '100000' ), DateWindow( start = date( 2029, 1, 1 ) ) ),
        ) )
        reader = _run( bonus, end_year = 2030 )
        payable = reader.chart.system_account( _PAYABLE )
        # Spike year: the estimate is capped at the prior (ordinary) year, so the bonus tax floats.
        self.assertLess(
            _cash_out( reader, 'Estimated income tax (prepayment)', 2028 ), _income_tax_expense( reader, 2028 ) )
        owed_2028 = reader.ledger.natural_balance( payable, through = date( 2028, 12, 31 ) )
        self.assertGreater( owed_2028, _D( '0' ) )
        # The floated balance is actually paid the next April -- it is not stranded on the payable.
        self.assertEqual( _cash_out( reader, 'Prior-year tax settlement', 2029 ), owed_2028 )
        # Year after: the anomalously high prior year does NOT over-charge it -- the estimate tracks
        # 2029's own (ordinary) liability, so its prepayment equals its true tax and it owes nothing.
        self.assertEqual(
            _cash_out( reader, 'Estimated income tax (prepayment)', 2029 ), _income_tax_expense( reader, 2029 ) )
        self.assertEqual( reader.ledger.natural_balance( payable, through = date( 2029, 12, 31 ) ), _D( '0' ) )

    def test_fica_is_withheld_in_year_not_deferred( self ):
        reader = _run( _CONSTANT )
        fica = reader.chart.expense_account( ExpenseTaxClass.EMPLOYMENT_TAX )
        self.assertGreater(
            reader.ledger.natural_flow( fica, start = date( 2026, 1, 1 ), end = date( 2026, 12, 31 ) ), _D( '0' ) )
        self.assertGreater( _cash_out( reader, 'FICA withholding', 2026 ), _D( '0' ) )

    def test_solvent_forecast_never_shows_negative_savings( self ):
        # Regression for the #170 bug: tax lumped at year-end (or floated whole to next April) could
        # punch a solvent household's Cash & Savings below zero. With tax paid in-year before funding,
        # the back-dated draw covers it, so cash stays at/above the floor every year the plan survives.
        reader = _run_drawdown()
        cash = reader.chart.cash_account()
        for year in range( 2026, 2031 ):
            self.assertGreaterEqual(
                reader.ledger.natural_balance( cash, through = date( year, 12, 31 ) ), _D( '0' ),
                f'Cash & Savings went negative at {year}-12-31 in a solvent forecast' )

    def test_terminal_year_tax_stands_as_an_unpaid_payable( self ):
        # The final year's tax accrues at its Dec 31 close, but its settlement date (the next April)
        # lies beyond the horizon, so it is deliberately left standing as a real liability -- which is
        # what depresses terminal net worth. Pin that behavior so a future change cannot silently drop
        # or double-settle it.
        reader = _run( _CONSTANT, wage_growth = '0.05' )
        payable = reader.chart.system_account( _PAYABLE )
        terminal = reader.ledger.natural_balance( payable, through = date( 2028, 12, 31 ) )
        self.assertGreater( terminal, _D( '0' ) )   # 2028's balance owed, never settled within the run
        self.assertEqual(
            [ txn for txn in reader.books.transactions
              if txn.description == 'Prior-year tax settlement' and txn.transaction_date.year > 2028 ], [] )
        # Terminal net worth is exactly assets net of that standing payable (the only liability here).
        self.assertEqual(
            reader.ledger.net_worth( through = date( 2028, 12, 31 ) ),
            reader.ledger.type_total( AccountType.ASSET, through = date( 2028, 12, 31 ) ) - terminal )

    def test_a_taxable_funding_draw_defers_its_gain_tax_to_the_payable( self ):
        # The estimate is assessed pre-draw, the settlement post-draw. When a funding draw realizes a
        # capital gain, the settlement's tax exceeds what was prepaid, and the difference -- the draw's
        # own tax -- is what defers to the payable (the loop-break the pre-draw assessment exists for).
        reader = _run_gainful_drawdown()
        payable = reader.chart.system_account( _PAYABLE )
        self.assertLess(
            _cash_out( reader, 'Estimated income tax (prepayment)', 2027 ),
            _income_tax_expense( reader, 2027 ) )
        self.assertGreater( reader.ledger.natural_balance( payable, through = date( 2027, 12, 31 ) ), _D( '0' ) )

    def test_an_early_withdrawal_penalty_rides_the_payable_not_cash( self ):
        reader = _run_retirement_drawdown()
        penalty_account = reader.chart.expense_account( ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY )
        cash = reader.chart.cash_account()
        payable = reader.chart.system_account( _PAYABLE )
        # A penalty is incurred (young owner drawing pre-tax) ...
        self.assertGreater(
            reader.ledger.natural_flow( penalty_account, start = date( 2026, 1, 1 ), end = date( 2026, 12, 31 ) ),
            _D( '0' ) )
        # ... and every penalty charge credits Taxes Payable, never cash -- it defers like the tax,
        # rather than being a same-year cash outflow.
        penalty_txns = [ txn for txn in reader.books.transactions
                         if any( entry.account is penalty_account for entry in txn.entries ) ]
        self.assertTrue( penalty_txns )
        for txn in penalty_txns:
            accounts = { entry.account for entry in txn.entries }
            self.assertIn( payable, accounts )
            self.assertNotIn( cash, accounts )

    def test_a_refund_receivable_is_collected_at_settlement( self ):
        # A refundable credit beyond the tax leaves Taxes Payable negative (a receivable). The
        # settlement entry is sign-agnostic, so it collects the refund IN (cash rises) rather than
        # paying out. No forecast input produces a net credit today, so drive the seam directly with a
        # seeded negative payable.
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        cash = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        taxes_payable = chart.system_account( _PAYABLE )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        bookkeeper.record( date( 2026, 12, 31 ), [ ( cash, -_D( '10000' ) ), ( opening, _D( '10000' ) ) ] )
        bookkeeper.record( date( 2026, 12, 31 ), [ ( taxes_payable, -_D( '500' ) ), ( opening, _D( '500' ) ) ] )

        parameters = PeriodParameters(
            date_span     = DateSpan( date( 2027, 1, 1 ), date( 2027, 12, 31 ) ),
            tax_context   = TaxContext( FilingStatus.SINGLE ),
            asset_rates   = AssetRates(),
            funding_policy = FundingPolicy(),
            tax_engine    = ZeroTaxEngine() )
        Period( parameters )._pay_prior_tax_payable( bookkeeper, PeriodResult() )

        self.assertEqual( bookkeeper.ledger.natural_balance( taxes_payable ), _D( '0' ) )   # receivable cleared
        self.assertEqual( bookkeeper.ledger.natural_balance( cash ), _D( '10500' ) )        # refund collected in


if __name__ == '__main__':
    unittest.main()
