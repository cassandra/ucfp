"""Tests for liabilities: a loan seeded at t0 and amortized monthly over its term.

Loans amortize monthly at any run granularity (each interval rolls up the months it spans), so
year-one interest is monthly-compounded on a declining balance -- a little under the flat
balance x rate. Covers the opening balance in net worth, that monthly-compounded interest, full
amortization to zero by the term (with the final payment capped to the remaining balance), a term
that is not a whole number of run-granularity periods (a mid-period origination), and a scheduled
payoff that extinguishes the remaining balance at a date and stops further amortization.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    LoanParameters,
    ScheduledLoanPayoff,
    Subject,
)
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection


def _parameters( end_date, events = () ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end_date,
        filing_status = FilingStatus.MARRIED_JOINT,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
        loans         = [ LoanParameters(
            'Mortgage', Decimal( '200000' ), Rate( Decimal( '0.05' ) ),
            Duration( 30, TimeUnit.YEAR ), ExpenseTaxClass.MORTGAGE_INTEREST,
            handle = 'mortgage', interest_handle = 'mortgage-interest' ) ],
        events        = list( events ),
    )


def _account( reader, handle ):
    return reader.chart.account( handle )


class LiabilityTests( unittest.TestCase ):

    def test_opening_balance_reduces_net_worth( self ):
        reader = Bookkeeper( Forecast( _parameters( date( 2026, 12, 31 ) ) ).run().books )
        # opening (day before the start): $500k cash less the $200k mortgage
        self.assertEqual( reader.ledger.net_worth( through = date( 2025, 12, 31 ) ), Decimal( '300000' ) )

    def test_first_year_interest_is_monthly_compounded( self ):
        # Twelve monthly steps at 5%/12 on a declining balance accrue a little under the flat
        # 200000 x 5% = 10000 of simple annual interest (~9933), and the balance falls.
        reader = Bookkeeper( Forecast( _parameters( date( 2026, 12, 31 ) ) ).run().books )
        interest = reader.ledger.natural_balance( _account( reader, 'mortgage-interest' ) )
        self.assertLess( interest, Decimal( '10000' ) )
        self.assertGreater( interest, Decimal( '9900' ) )
        self.assertLess(
            reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '200000' ) )

    def test_loan_amortizes_to_zero_by_the_term( self ):
        # run past the 30-year term; the level payment retires the balance, final payment capped
        reader = Bookkeeper( Forecast( _parameters( date( 2060, 12, 31 ) ) ).run().books )
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )


class LoanPayoffTests( unittest.TestCase ):
    """A scheduled payoff extinguishes the loan's projected remaining balance at its date,
    funded from cash, and the loan stops amortizing thereafter."""

    _PAYOFF = ScheduledLoanPayoff( date( 2030, 6, 1 ), 'mortgage' )

    def test_payoff_zeroes_balance_well_before_the_term( self ):
        # Without the payoff the 30-year mortgage still has a balance in 2035; with it, zero --
        # and the payoff transaction balances, so the liability reduction was funded from cash.
        reader = Bookkeeper( Forecast( _parameters( date( 2035, 12, 31 ) ) ).run().books )
        self.assertGreater(
            reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )
        paid = Bookkeeper(
            Forecast( _parameters( date( 2035, 12, 31 ), [ self._PAYOFF ] ) ).run().books )
        paid.assert_balanced()
        self.assertEqual( paid.ledger.natural_balance( _account( paid, 'mortgage' ) ), Decimal( '0' ) )

    def test_early_payoff_saves_interest_raising_net_worth( self ):
        # Clearing the loan early stops its interest expense, so terminal net worth is higher than
        # letting it amortize on (the cash used would otherwise just sit, not earn).
        without = Bookkeeper( Forecast( _parameters( date( 2035, 12, 31 ) ) ).run().books )
        paid = Bookkeeper(
            Forecast( _parameters( date( 2035, 12, 31 ), [ self._PAYOFF ] ) ).run().books )
        self.assertGreater( paid.ledger.net_worth(), without.ledger.net_worth() )

    def test_amortization_stops_after_payoff( self ):
        # Interest accrues only until the payoff, so total interest is less than without it.
        without = Bookkeeper( Forecast( _parameters( date( 2035, 12, 31 ) ) ).run().books )
        paid = Bookkeeper(
            Forecast( _parameters( date( 2035, 12, 31 ), [ self._PAYOFF ] ) ).run().books )
        self.assertLess(
            paid.ledger.natural_balance( _account( paid, 'mortgage-interest' ) ),
            without.ledger.natural_balance( _account( without, 'mortgage-interest' ) ) )

    def test_payoff_after_full_amortization_is_a_noop( self ):
        # The term retires the loan by ~2056; a payoff in 2058 sees a zero balance and posts
        # nothing, leaving the books balanced.
        late_payoff = ScheduledLoanPayoff( date( 2058, 6, 1 ), 'mortgage' )
        reader = Bookkeeper(
            Forecast( _parameters( date( 2059, 12, 31 ), [ late_payoff ] ) ).run().books )
        reader.assert_balanced()
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )

    def test_payoff_naming_an_unknown_loan_is_skipped( self ):
        # A payoff of a loan account that never materialized (a sold vehicle whose loan has no terms, or a
        # loan already cleared) has nothing to extinguish, so it is a no-op and the run completes rather
        # than failing -- closing #150. A non-liability handle is still rejected (below).
        skipped = ScheduledLoanPayoff( date( 2030, 6, 1 ), 'no-such-loan' )
        self.assertIsNotNone( Forecast( _parameters( date( 2030, 12, 31 ), [ skipped ] ) ).run() )

    def test_payoff_naming_a_non_liability_is_rejected( self ):
        # The mortgage's own interest expense account carries a handle but is not a liability.
        non_liability = ScheduledLoanPayoff( date( 2030, 6, 1 ), 'mortgage-interest' )
        with self.assertRaises( MissingAccountError ):
            Forecast( _parameters( date( 2030, 12, 31 ), [ non_liability ] ) ).run()


class NonAlignedTermTests( unittest.TestCase ):
    """A loan term that is not a whole number of run-granularity periods -- a mortgage originated
    mid-period leaves e.g. 233 months -- forecasts at annual granularity. Loans amortize monthly,
    so the term need not align to the period (this run was previously rejected outright)."""

    def _parameters( self, term_months, end_date ):
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = end_date,
            filing_status = FilingStatus.MARRIED_JOINT,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
            assets        = [ AssetParameters(
                'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
            loans         = [ LoanParameters(
                'Mortgage', Decimal( '200000' ), Rate( Decimal( '0.05' ) ),
                Duration( term_months, TimeUnit.MONTH ), ExpenseTaxClass.MORTGAGE_INTEREST,
                handle = 'mortgage', interest_handle = 'mortgage-interest' ) ],
        )

    def test_non_period_aligned_term_runs_at_annual_granularity( self ):
        # 233 months is not a multiple of 12; at annual granularity this once raised ValueError.
        reader = Bookkeeper( Forecast( self._parameters( 233, date( 2026, 12, 31 ) ) ).run().books )
        self.assertGreater(
            reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )

    def test_non_period_aligned_term_amortizes_to_zero( self ):
        # 233 months from 2026-01 retires the loan by ~2045-06; run past it -> fully paid off.
        reader = Bookkeeper( Forecast( self._parameters( 233, date( 2046, 12, 31 ) ) ).run().books )
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
