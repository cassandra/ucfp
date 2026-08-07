"""A loan that originates mid-forecast (issue #136): dormant until its date, then borrowed and
amortized from there -- the recurring-financing counterpart of a t0 loan.

An originated loan's accounts exist from the start but carry nothing until `origination_date`, when
its principal is credited to the liability and the proceeds land in cash (a balanced borrow, no
equity plug). Amortization then runs over the loan's term from origination -- and, because the
origination span amortizes from the declared principal for only the months after the borrow, the
schedule is identical at any run granularity (the invariant the engine guarantees for t0 loans, now
extended to originated ones). Covers dormancy, the borrow landing in cash net worth-neutrally, full
amortization by origination + term, granularity invariance, and books that stay balanced.
"""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    LoanParameters,
    ScheduledLoanPayoff,
    ScheduledPurchase,
    Subject,
)
from ucfp.forecast.tests.granularity_harness import ANNUAL, MONTHLY, run_at
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_ORIGINATION = date( 2030, 6, 1 )
_PRINCIPAL   = Decimal( '30000' )


def _parameters( end_date, *, origination_date = _ORIGINATION, principal = _PRINCIPAL,
                 term_years = 5, with_loan = True ):
    loans = [ LoanParameters(
        'Car', principal, Rate( Decimal( '0.06' ) ), Duration( term_years, TimeUnit.YEAR ),
        ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST, handle = 'car', interest_handle = 'car-interest',
        origination_date = origination_date ) ] if with_loan else []
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end_date,
        filing_status = FilingStatus.MARRIED_JOINT,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
        loans         = loans,
    )


def _account( reader, handle ):
    return reader.chart.account( handle )


class OriginatedLoanTests( unittest.TestCase ):

    def test_dormant_before_its_origination_date( self ):
        # Run to the end of the year before origination: the loan's accounts exist but carry no
        # balance and no interest -- it is not yet a debt.
        reader = Bookkeeper( Forecast( _parameters( date( 2029, 12, 31 ) ) ).run().books )
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'car' ) ), Decimal( '0' ) )
        self.assertEqual(
            reader.ledger.natural_balance( _account( reader, 'car-interest' ) ), Decimal( '0' ) )

    def test_borrowed_and_amortizing_after_origination( self ):
        # A year and a half in, the balance is real, below the principal (paying down), and interest
        # has accrued only since origination.
        reader = Bookkeeper( Forecast( _parameters( date( 2031, 12, 31 ) ) ).run().books )
        balance = reader.ledger.natural_balance( _account( reader, 'car' ) )
        self.assertGreater( balance, Decimal( '0' ) )
        self.assertLess( balance, _PRINCIPAL )
        self.assertGreater(
            reader.ledger.natural_balance( _account( reader, 'car-interest' ) ), Decimal( '0' ) )

    def test_the_borrow_is_net_worth_neutral_but_for_interest( self ):
        # The origination itself just swaps a liability for cash, so at year-end the only dent in net
        # worth versus having no loan is the interest accrued since June -- the principal neither
        # created nor destroyed wealth. Books stay balanced through the borrow.
        with_loan    = Bookkeeper( Forecast( _parameters( date( 2030, 12, 31 ) ) ).run().books )
        without_loan = Bookkeeper(
            Forecast( _parameters( date( 2030, 12, 31 ), with_loan = False ) ).run().books )
        with_loan.assert_balanced()
        interest = with_loan.ledger.natural_balance( _account( with_loan, 'car-interest' ) )
        self.assertGreater( interest, Decimal( '0' ) )
        gap = without_loan.ledger.net_worth() - with_loan.ledger.net_worth()
        self.assertAlmostEqual( gap, interest, delta = Decimal( '1' ) )

    def test_amortizes_to_zero_by_origination_plus_term( self ):
        # Originated 2030-06 over five years -> retired by ~2035-06; run past it and the balance is
        # gone (the final payment capped to what remained).
        reader = Bookkeeper( Forecast( _parameters( date( 2036, 12, 31 ) ) ).run().books )
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'car' ) ), Decimal( '0' ) )

    def test_not_seeded_into_opening_net_worth( self ):
        # A t0 loan reduces day-one net worth; an originated loan does not -- at the opening date the
        # $500k cash stands alone, the car loan still ahead.
        reader = Bookkeeper( Forecast( _parameters( date( 2030, 12, 31 ) ) ).run().books )
        self.assertEqual(
            reader.ledger.net_worth( through = date( 2025, 12, 31 ) ), Decimal( '500000' ) )


class OriginatedLoanGranularityTests( unittest.TestCase ):
    """The origination-span amortization is derived from the principal over the months after the
    borrow, so an originated loan amortizes identically at any granularity -- the same invariant t0
    loans hold. Compare the liability trajectory and net worth year-by-year, annual vs monthly."""

    def test_liability_and_net_worth_match_annual_vs_monthly( self ):
        parameters = _parameters( date( 2037, 12, 31 ) )
        annual  = Bookkeeper( run_at( parameters, ANNUAL ).books )
        monthly = Bookkeeper( run_at( parameters, MONTHLY ).books )
        car = 'car'
        for year in range( 2029, 2038 ):                       # spanning dormant, active, paid-off
            through = date( year, 12, 31 )
            annual_balance  = annual.ledger.natural_balance( _account( annual, car ), through = through )
            monthly_balance = monthly.ledger.natural_balance( _account( monthly, car ), through = through )
            self.assertAlmostEqual(
                annual_balance, monthly_balance, delta = Decimal( '1' ),
                msg = f'{year}: loan balance {annual_balance} (annual) vs {monthly_balance} (monthly)' )
            annual_nw  = annual.ledger.net_worth( through = through )
            monthly_nw = monthly.ledger.net_worth( through = through )
            self.assertAlmostEqual(
                annual_nw, monthly_nw, delta = Decimal( '1' ),
                msg = f'{year}: net worth {annual_nw} (annual) vs {monthly_nw} (monthly)' )
            continue


class OriginatedLoanCompositionTests( unittest.TestCase ):
    """Origination composes with the other money-movement primitives into the financed-purchase and
    replacement-cycle shapes #130 builds on -- proven here at the engine level so #130 can rely on it."""

    def _financed_purchase_parameters( self, end_date, *, price, down ):
        # A car holding opening at zero to buy into, a purchase for the full price, and a loan for the
        # financed remainder -- all on the same date. The classic financed acquisition.
        return replace(
            _parameters( end_date, principal = price - down ),
            assets = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ),
                AssetParameters( 'Car', AssetClass.DEPRECIATING, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'car-asset' ) ],
            events = [ ScheduledPurchase( _ORIGINATION, 'car-asset', price ) ] )

    def test_financed_purchase_nets_cash_to_the_down_payment( self ):
        # Borrow (price - down) to cash, spend price on the car: the net cash outlay is exactly the
        # down payment, and the acquisition is net worth-neutral (asset gained, liability + cash spent).
        price, down = Decimal( '30000' ), Decimal( '6000' )
        before = Bookkeeper(
            Forecast( self._financed_purchase_parameters( date( 2029, 12, 31 ), price = price, down = down ) )
            .run().books )
        after = Bookkeeper(
            Forecast( self._financed_purchase_parameters( date( 2030, 12, 31 ), price = price, down = down ) )
            .run().books )
        after.assert_balanced()
        cash_drop = ( before.ledger.natural_balance( before.chart.cash_account() )
                      - after.ledger.natural_balance( after.chart.cash_account() ) )
        # Cash falls by the down payment plus the part-year loan payments since June (interest + a
        # little principal); isolate the down payment by netting the loan balance and interest back.
        loan_balance = after.ledger.natural_balance( _account( after, 'car' ) )
        interest     = after.ledger.natural_balance( _account( after, 'car-interest' ) )
        principal_paid = ( price - down ) - loan_balance
        self.assertAlmostEqual(
            cash_drop - principal_paid - interest, down, delta = Decimal( '1' ) )

    def test_settle_and_reoriginate_cycle( self ):
        # The replacement shape: pay off the outgoing loan and originate the next on the same date.
        # After the cycle date the first loan is gone and the second is a fresh, amortizing balance.
        first  = LoanParameters(
            'Car 1', Decimal( '24000' ), Rate( Decimal( '0.06' ) ), Duration( 5, TimeUnit.YEAR ),
            ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST, handle = 'car1', interest_handle = 'car1-interest',
            origination_date = date( 2030, 6, 1 ) )
        second = LoanParameters(
            'Car 2', Decimal( '28000' ), Rate( Decimal( '0.06' ) ), Duration( 5, TimeUnit.YEAR ),
            ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST, handle = 'car2', interest_handle = 'car2-interest',
            origination_date = date( 2035, 6, 1 ) )
        parameters = replace(
            _parameters( date( 2036, 12, 31 ), with_loan = False ),
            loans  = [ first, second ],
            events = [ ScheduledLoanPayoff( date( 2035, 6, 1 ), 'car1' ) ] )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        reader.assert_balanced()
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'car1' ) ), Decimal( '0' ) )
        second_balance = reader.ledger.natural_balance( _account( reader, 'car2' ) )
        self.assertGreater( second_balance, Decimal( '0' ) )
        self.assertLess( second_balance, Decimal( '28000' ) )


class OriginatedLoanEdgeTests( unittest.TestCase ):

    def test_origination_in_the_final_period_borrows_but_defers_payment( self ):
        # Origination in the last month of the horizon: the balance is credited (near the full
        # principal, no payment yet) and the books balance -- payments would start the next period.
        reader = Bookkeeper(
            Forecast( _parameters( date( 2030, 12, 31 ), origination_date = date( 2030, 12, 1 ) ) )
            .run().books )
        reader.assert_balanced()
        self.assertEqual(
            reader.ledger.natural_balance( _account( reader, 'car' ) ), _PRINCIPAL )
        self.assertEqual(
            reader.ledger.natural_balance( _account( reader, 'car-interest' ) ), Decimal( '0' ) )

    def test_origination_then_immediate_payoff_is_net_neutral( self ):
        # Borrow, then pay it right back off a month later: the liability ends at zero, only a sliver
        # of interest was spent, and the books balance.
        parameters = replace(
            _parameters( date( 2031, 12, 31 ) ),
            events = [ ScheduledLoanPayoff( date( 2030, 8, 1 ), 'car' ) ] )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        reader.assert_balanced()
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'car' ) ), Decimal( '0' ) )

    def test_origination_after_the_horizon_never_fires( self ):
        # A loan whose origination date is past the run's end simply never becomes a debt: no balance,
        # no interest, books balanced -- the mirror of a payoff dated after the term.
        reader = Bookkeeper(
            Forecast( _parameters( date( 2029, 12, 31 ), origination_date = date( 2035, 6, 1 ) ) )
            .run().books )
        reader.assert_balanced()
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'car' ) ), Decimal( '0' ) )

    def test_origination_before_the_start_is_rejected( self ):
        # An originated loan dated before the forecast start would never fire (it falls in no period),
        # silently mismodelling; reject it so the planner sets it as a t0 loan instead.
        with self.assertRaises( ValueError ):
            _parameters( date( 2030, 12, 31 ), origination_date = date( 2025, 6, 1 ) )


if __name__ == '__main__':
    unittest.main()
