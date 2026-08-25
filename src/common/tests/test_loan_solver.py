"""Tests for the shared loan solver -- the plausibility-guarded back-solve and the rate resolution every
loan-entry surface relies on. The raw amortization is pinned in `test_amortization`; here we pin the
guard and the resolution rules layered over it."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.amortization import level_payment
from common.loan_solver import (
    MAX_PLAUSIBLE_APR, monthly_payment, plausible_rate_from_payment, resolved_annual_rate )
from common.rate import Rate


class MonthlyPaymentTest( SimpleTestCase ):

    def test_it_is_the_level_payment_at_the_monthly_rate( self ):
        # 18,000 at 6%/yr (0.5%/month) over 36 months -- the rate view turned into the payment view.
        expected = level_payment( Decimal( '18000' ), Decimal( '0.06' ) / 12, 36 )
        self.assertEqual( monthly_payment( Decimal( '18000' ), Rate.percent( 6 ), 36 ), expected )

    def test_zero_rate_is_straight_line( self ):
        self.assertEqual( monthly_payment( Decimal( '1200' ), Rate( Decimal( '0' ) ), 12 ),
                          Decimal( '100' ) )


class PlausibleRateFromPaymentTest( SimpleTestCase ):
    """The guard on the monthly-derived rate: below the ~30% APR cap it back-solves a `Rate`, above it (or
    when the payments cannot even retire the balance) it declines rather than fabricate a bogus rate."""

    def test_a_plausible_monthly_back_solves_to_a_rate( self ):
        payment = monthly_payment( Decimal( '20000' ), Rate.percent( 5 ), 36 )
        rate    = plausible_rate_from_payment( Decimal( '20000' ), payment, 36 )
        self.assertIsNotNone( rate )
        self.assertLess( rate.fraction, MAX_PLAUSIBLE_APR.fraction )

    def test_a_round_trip_recovers_the_rate( self ):
        payment = monthly_payment( Decimal( '20000' ), Rate.percent( 5 ), 36 )
        rate    = plausible_rate_from_payment( Decimal( '20000' ), payment, 36 )
        self.assertEqual( round( rate.fraction, 4 ), Decimal( '0.0500' ) )

    def test_an_implausibly_high_monthly_yields_no_rate( self ):
        # ~60% APR on 20,000 over 36 months -- beyond a real loan, so no rate is fabricated.
        high = monthly_payment( Decimal( '20000' ), Rate.percent( 60 ), 36 )
        self.assertIsNone( plausible_rate_from_payment( Decimal( '20000' ), high, 36 ) )

    def test_a_zero_interest_monthly_is_the_boundary( self ):
        # Exactly the straight-line payment implies a 0% loan (the lowest plausible rate).
        rate = plausible_rate_from_payment( Decimal( '18000' ), Decimal( '500' ), 36 )   # 18,000 / 36
        self.assertEqual( rate, Rate( Decimal( '0' ) ) )

    def test_a_monthly_that_cannot_retire_the_balance_yields_no_rate( self ):
        # 400/mo x 36 = 14,400 < 18,000 -- the payments never clear the balance, so no rate fits.
        self.assertIsNone( plausible_rate_from_payment( Decimal( '18000' ), Decimal( '400' ), 36 ) )


class ResolvedAnnualRateTest( SimpleTestCase ):
    """Which term the user gave wins: a directly-entered rate stands as-is; otherwise the rate is
    back-solved from the payment; when neither is usable, there is no rate yet."""

    def test_an_entered_rate_is_used_verbatim( self ):
        # The entered rate stands even when a payment is also present -- it is authoritative.
        self.assertEqual(
            resolved_annual_rate( Rate.percent( 6 ), Decimal( '20000' ), Decimal( '999' ), 36 ),
            Rate.percent( 6 ) )

    def test_it_back_solves_from_the_payment_when_no_rate_entered( self ):
        payment = monthly_payment( Decimal( '20000' ), Rate.percent( 5 ), 36 )
        rate    = resolved_annual_rate( None, Decimal( '20000' ), payment, 36 )
        self.assertEqual( round( rate.fraction, 4 ), Decimal( '0.0500' ) )

    def test_no_rate_and_no_usable_payment_resolves_to_none( self ):
        self.assertIsNone( resolved_annual_rate( None, Decimal( '20000' ), None, 36 ) )

    def test_a_zero_or_missing_balance_resolves_to_none( self ):
        self.assertIsNone( resolved_annual_rate( None, Decimal( '0' ), Decimal( '500' ), 36 ) )
        self.assertIsNone( resolved_annual_rate( None, None, Decimal( '500' ), 36 ) )

    def test_an_implausible_payment_resolves_to_none( self ):
        high = monthly_payment( Decimal( '20000' ), Rate.percent( 60 ), 36 )
        self.assertIsNone( resolved_annual_rate( None, Decimal( '20000' ), high, 36 ) )
