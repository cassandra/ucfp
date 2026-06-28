"""Tests for the loan amortization utility -- stable, domain-agnostic math worth pinning."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.amortization import level_payment, remaining_balance


class LevelPaymentTest( SimpleTestCase ):

    def test_zero_rate_is_straight_line( self ):
        self.assertEqual( level_payment( Decimal( '1200' ), Decimal( '0' ), 12 ), Decimal( '100' ) )

    def test_known_amortization( self ):
        # 1000 at 10%/period over 2 periods -> 576.19 per period.
        payment = level_payment( Decimal( '1000' ), Decimal( '0.1' ), 2 )
        self.assertEqual( round( payment, 2 ), Decimal( '576.19' ) )


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
