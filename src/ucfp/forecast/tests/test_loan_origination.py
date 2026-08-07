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


if __name__ == '__main__':
    unittest.main()
