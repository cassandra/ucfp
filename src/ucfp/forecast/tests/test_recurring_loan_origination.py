"""RecurringLoanOrigination: the engine expands a recurring loan itself -- the financing analog of a
recurring holding purchase (a car refinanced at each replacement). Over the window at the cadence it
originates a fresh per-cycle loan whose principal is inflated to that year's nominal, and it
intrinsically pays off the prior cycle's loan at each new origination (the outgoing car's loan, cleared
at trade-in). Expanded once at setup into per-cycle `LoanParameters` and rollover payoffs, so the
existing origination and amortization machinery drives them unchanged.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, RecurringLoanOrigination, ScheduledLoanPayoff, Subject )
from ucfp.forecast.tests.granularity_harness import ANNUAL, MONTHLY, run_at
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


def _params( *, end : date, economics : EconomicParameters, originations : list,
             cash : str = '500000' ) -> ForecastParameters:
    """A minimal run: a cash hub to receive each borrow and fund amortization, plus the recurring loan."""
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end,
        filing_status = FilingStatus.SINGLE,
        statute       = _STATUTE,
        subjects      = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( cash ), Decimal( cash ), handle = 'cash' ) ],
        economic_outlook = EconomicOutlook.constant( economics ),
        recurring_loan_originations = originations )


def _loan( **fields ) -> RecurringLoanOrigination:
    defaults = dict(
        name = 'Car loan', principal = Decimal( '25000' ), interest_rate = Rate( Decimal( '0.06' ) ),
        term = Duration( 10, TimeUnit.YEAR ), interval = Duration( 5, TimeUnit.YEAR ),
        handle = 'carloan', interest_handle = 'carloan-int' )
    defaults.update( fields )
    return RecurringLoanOrigination( **defaults )


class RecurringLoanOriginationTests( unittest.TestCase ):

    def test_expands_into_per_cycle_loans_with_inflated_principal( self ):
        # 10% inflation, replaced every 5 years from 2027 over a 2035 horizon -> cycles 0 (2027) and 1
        # (2032), each its own liability + interest account, the principal inflated to its year.
        params = _params(
            end          = date( 2035, 12, 31 ),
            economics    = EconomicParameters( inflation = Rate( Decimal( '0.10' ) ) ),
            originations = [ _loan( window = DateWindow( start = date( 2027, 1, 1 ) ) ) ] )
        loans = { loan.handle : loan for loan in Forecast( params )._parameters.loans }
        self.assertEqual( set( loans ), { 'carloan:0', 'carloan:1' } )
        self.assertEqual( loans[ 'carloan:0' ].origination_date, date( 2027, 1, 1 ) )
        self.assertEqual( loans[ 'carloan:1' ].origination_date, date( 2032, 1, 1 ) )
        self.assertEqual( loans[ 'carloan:0' ].interest_handle, 'carloan-int:0' )
        self.assertEqual( loans[ 'carloan:0' ].opening_balance, Decimal( '27500.0' ) )       # 25,000 x 1.1
        self.assertGreater( loans[ 'carloan:1' ].opening_balance,                            # x 1.1^6, dearer
                            loans[ 'carloan:0' ].opening_balance )

    def test_rollover_pays_off_the_prior_cycles_loan( self ):
        # Inflation off, to isolate the rollover. The 10-year loan still owes at the 5-year replacement, so
        # the 2032 origination settles the 2027 loan (a real, non-zero payoff), then owes on the fresh one.
        params = _params(
            end          = date( 2035, 12, 31 ),
            economics    = EconomicParameters(),
            originations = [ _loan( window = DateWindow( start = date( 2027, 1, 1 ) ) ) ] )
        forecast = Forecast( params )
        payoffs  = [ ( e.event_date, e.loan ) for e in forecast._parameters.events
                     if isinstance( e, ScheduledLoanPayoff ) ]
        self.assertEqual( payoffs, [ ( date( 2032, 1, 1 ), 'carloan:0' ) ] )   # cycle 1 settles cycle 0
        reader = Bookkeeper( forecast.run().books )
        reader.assert_balanced()
        self.assertEqual( reader.ledger.natural_balance( reader.chart.account( 'carloan:0' ),
                                                         through = date( 2033, 12, 31 ) ), Decimal( '0' ) )
        self.assertGreater( reader.ledger.natural_balance( reader.chart.account( 'carloan:1' ),
                                                           through = date( 2033, 12, 31 ) ), Decimal( '0' ) )

    def test_annual_and_monthly_runs_agree_on_loan_balances( self ):
        # Loans amortize monthly at any granularity and the principal inflation is annual-indexed, so each
        # per-cycle liability balance tracks across grains. Net worth is not asserted across the rollover:
        # a loan paid off in the span it amortizes carries a granularity-sensitive interest cost (the
        # same-span-payoff simplification the loan-origination work documented), which nets into cash.
        params = _params(
            end          = date( 2035, 12, 31 ),
            economics    = EconomicParameters( inflation = Rate( Decimal( '0.03' ) ) ),
            originations = [ _loan( window = DateWindow( start = date( 2027, 1, 1 ) ) ) ] )
        annual  = Bookkeeper( run_at( params, ANNUAL ).books )
        monthly = Bookkeeper( run_at( params, MONTHLY ).books )
        for handle in ( 'carloan:0', 'carloan:1' ):
            annual_loan  = annual.chart.account( handle )
            monthly_loan = monthly.chart.account( handle )
            for year in range( 2027, 2036 ):
                through = date( year, 12, 31 )
                self.assertAlmostEqual(
                    annual.ledger.natural_balance( annual_loan, through = through ),
                    monthly.ledger.natural_balance( monthly_loan, through = through ),
                    delta = Decimal( '1' ), msg = f'{handle} {year}: balance annual vs monthly' )
                continue
            continue

    def test_occurrences_before_the_run_start_are_skipped( self ):
        # A vehicle whose next purchase predates the run start must not originate a pre-start loan (the
        # parameters reject that) -- the engine clips to occurrences on or after the start, like the
        # holding path, so construction does not raise and only the in-range cycles originate.
        params = _params(
            end          = date( 2040, 12, 31 ),
            economics    = EconomicParameters(),
            originations = [ _loan( window = DateWindow( start = date( 2024, 1, 1 ) ) ) ] )   # start = 2026
        forecast = Forecast( params )                                      # must not raise
        self.assertEqual(                                                  # 2024 dropped; 2029/2034/2039 kept
            [ loan.origination_date for loan in forecast._parameters.loans ],
            [ date( 2029, 1, 1 ), date( 2034, 1, 1 ), date( 2039, 1, 1 ) ] )

    def test_a_window_without_a_start_is_rejected( self ):
        with self.assertRaises( ValueError ):
            _loan( window = DateWindow( end = date( 2035, 1, 1 ) ) )

    def test_a_non_positive_interval_is_rejected( self ):
        with self.assertRaises( ValueError ):
            _loan( interval = Duration( 0, TimeUnit.YEAR ),
                   window = DateWindow( start = date( 2027, 1, 1 ) ) )


if __name__ == '__main__':
    unittest.main()
