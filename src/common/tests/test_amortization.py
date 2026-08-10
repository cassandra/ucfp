"""Tests for the loan amortization utility -- stable, domain-agnostic math worth pinning."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.amortization import (
    balance_after, level_payment, periods_to_repay, present_value, rate_for_payment, remaining_balance )


class RateForPaymentTest( SimpleTestCase ):
    """The inverse of `level_payment` solved for the rate -- the current vehicle loan's rate from its
    (known) monthly payment and remaining term."""

    def test_it_recovers_the_rate_that_produced_a_payment( self ):
        # Round-trip: a payment amortizing 18,000 at 0.5%/month over 36 months back-solves to ~0.5%.
        payment = level_payment( Decimal( '18000' ), Decimal( '0.005' ), 36 )
        self.assertEqual( round( rate_for_payment( Decimal( '18000' ), payment, 36 ), 6 ),
                          Decimal( '0.005000' ) )

    def test_a_payment_at_the_zero_interest_level_is_zero_rate( self ):
        self.assertEqual( rate_for_payment( Decimal( '1200' ), Decimal( '100' ), 12 ), Decimal( '0' ) )

    def test_a_payment_below_the_zero_interest_level_is_zero_rate( self ):
        # A payment that does not even cover straight-line principal implies no positive rate.
        self.assertEqual( rate_for_payment( Decimal( '1200' ), Decimal( '90' ), 12 ), Decimal( '0' ) )


class LevelPaymentTest( SimpleTestCase ):

    def test_zero_rate_is_straight_line( self ):
        self.assertEqual( level_payment( Decimal( '1200' ), Decimal( '0' ), 12 ), Decimal( '100' ) )

    def test_known_amortization( self ):
        # 1000 at 10%/period over 2 periods -> 576.19 per period.
        payment = level_payment( Decimal( '1000' ), Decimal( '0.1' ), 2 )
        self.assertEqual( round( payment, 2 ), Decimal( '576.19' ) )


class PeriodsToRepayTest( SimpleTestCase ):

    def test_zero_balance_needs_no_payments( self ):
        self.assertEqual( periods_to_repay( Decimal( '0' ), Decimal( '0.015' ), Decimal( '100' ) ), 0 )

    def test_zero_rate_divides_and_rounds_up( self ):
        # 1000 at no interest, 300/period -> 4 periods (the last one partial).
        self.assertEqual( periods_to_repay( Decimal( '1000' ), Decimal( '0' ), Decimal( '300' ) ), 4 )

    def test_payment_below_interest_never_clears( self ):
        # 1% of 1000 is 10/period; paying 10 (or less) never reduces the balance.
        self.assertIsNone( periods_to_repay( Decimal( '1000' ), Decimal( '0.01' ), Decimal( '10' ) ) )
        self.assertIsNone( periods_to_repay( Decimal( '1000' ), Decimal( '0.01' ), Decimal( '5' ) ) )

    def test_paying_at_least_the_level_payment_clears_within_the_term( self ):
        # Paying a hair over the 2-period level payment clears 1000 @ 10% in 2 (the period whose
        # payment covers the full payoff clears it there).
        payment = level_payment( Decimal( '1000' ), Decimal( '0.1' ), 2 ) + Decimal( '0.01' )
        self.assertEqual( periods_to_repay( Decimal( '1000' ), Decimal( '0.1' ), payment ), 2 )

    def test_last_period_may_be_partial( self ):
        # 1000 @ 10%, paying 600/period: 1100-600=500, 550-600<=0 -> cleared in 2 (2nd is partial).
        self.assertEqual( periods_to_repay( Decimal( '1000' ), Decimal( '0.1' ), Decimal( '600' ) ), 2 )


class PresentValueTest( SimpleTestCase ):

    def test_zero_rate_is_payment_times_periods( self ):
        self.assertEqual( present_value( Decimal( '100' ), Decimal( '0' ), 12 ), Decimal( '1200' ) )

    def test_inverts_level_payment( self ):
        # The principal a payment retires round-trips: present_value(level_payment(P)) == P.
        principal = Decimal( '20000' )
        payment   = level_payment( principal, Decimal( '0.005' ), 60 )
        self.assertEqual( round( present_value( payment, Decimal( '0.005' ), 60 ), 2 ), principal )


class BalanceAfterTest( SimpleTestCase ):

    def test_zero_rate_subtracts_payments( self ):
        self.assertEqual(
            balance_after( Decimal( '1000' ), Decimal( '0' ), Decimal( '300' ), 2 ), Decimal( '400' ) )

    def test_clamps_at_zero_when_overpaid( self ):
        self.assertEqual(
            balance_after( Decimal( '1000' ), Decimal( '0' ), Decimal( '300' ), 10 ), Decimal( '0' ) )

    def test_interest_only_payment_holds_the_balance( self ):
        # Paying exactly the interest (1% of 1000 = 10) leaves the balance unchanged each period.
        self.assertEqual(
            balance_after( Decimal( '1000' ), Decimal( '0.01' ), Decimal( '10' ), 5 ), Decimal( '1000' ) )

    def test_partial_paydown_reduces_balance( self ):
        # 1000 @ 1%, paying 100/period for 3: 1010-100=910, 919.1-100=819.1, 827.291-100=727.291.
        self.assertEqual(
            balance_after( Decimal( '1000' ), Decimal( '0.01' ), Decimal( '100' ), 3 ),
            Decimal( '727.291' ) )


class RemainingBalanceTest( SimpleTestCase ):

    def test_full_principal_before_first_payment( self ):
        self.assertEqual(
            remaining_balance( Decimal( '1000' ), Decimal( '0.1' ), 2, 0 ), Decimal( '1000' ) )

    def test_zero_at_and_beyond_term( self ):
        self.assertEqual( remaining_balance( Decimal( '1000' ), Decimal( '0.1' ), 2, 2 ), Decimal( '0' ) )
        self.assertEqual( remaining_balance( Decimal( '1000' ), Decimal( '0.1' ), 2, 5 ), Decimal( '0' ) )

    def test_zero_rate_is_linear( self ):
        self.assertEqual(
            remaining_balance( Decimal( '1200' ), Decimal( '0' ), 12, 3 ), Decimal( '900' ) )

    def test_interior_balance( self ):
        # After 1 of 2 payments on the 1000 @ 10% loan: 1100 - 576.19 = 523.81.
        balance = remaining_balance( Decimal( '1000' ), Decimal( '0.1' ), 2, 1 )
        self.assertEqual( round( balance, 2 ), Decimal( '523.81' ) )

    def test_balance_one_period_before_end_is_discounted_final_payment( self ):
        # B(n-1) * (1+i) - payment = 0, so B(n-1) = payment / (1+i): the last payment, discounted.
        rate, periods, principal = Decimal( '0.005' ), 360, Decimal( '300000' )
        near_end = remaining_balance( principal, rate, periods, periods - 1 )
        payment  = level_payment( principal, rate, periods )
        self.assertEqual( round( near_end, 2 ), round( payment / ( Decimal( '1' ) + rate ), 2 ) )
