"""The ACA premium tax credit (#114): the 400%-of-FPL eligibility cliff and the actual-premium cap.
Exercises `_premium_tax_credit` directly with a controlled MAGI and enrollment, so the boundary and
cap behavior are isolated from the surrounding income tax the credit offsets."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.subsidized_health import SubsidizedHealthEnrollment
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D = Decimal


class PremiumTaxCreditCliffTest( unittest.TestCase ):
    """Above 400% FPL the reverted credit ends outright (a cliff, not a phase-out); at or below it a
    household enrolled in a benchmark-priced plan still receives a positive credit."""

    def setUp( self ):
        self.engine     = USFederalTaxEngine( federal_2026() )
        # Household of one: FPL 15,650, so the 400% cliff sits at 62,600 of MAGI. Actual premium equals
        # the benchmark, so the actual-premium cap does not interfere with the cliff assertions.
        self.enrollment = SubsidizedHealthEnrollment(
            household_size = 1, reference_premium = _D( '8000' ), actual_premium = _D( '8000' ) )
        self.fpl        = federal_2026().aca.poverty_line( 1 )

    def _credit_at_ratio( self, ratio ):
        return self.engine._premium_tax_credit( self.fpl * _D( ratio ), self.enrollment )

    def test_credit_is_paid_below_the_cliff( self ):
        self.assertGreater( self._credit_at_ratio( '3.9' ), _D( '0' ) )

    def test_credit_is_available_at_exactly_the_cliff( self ):
        # The cliff zeroes only ABOVE 400% FPL; exactly at it the household is still eligible.
        self.assertGreater( self._credit_at_ratio( '4.0' ), _D( '0' ) )

    def test_credit_is_zero_above_the_cliff( self ):
        self.assertEqual( self._credit_at_ratio( '4.1' ), _D( '0' ) )

    def test_cliff_zeroes_the_credit_even_with_a_cheap_plan( self ):
        # Above the cliff the credit is zero regardless of a cheap actual premium: the cliff
        # short-circuits before the actual-premium cap would apply.
        enrollment = SubsidizedHealthEnrollment(
            household_size = 1, reference_premium = _D( '8000' ), actual_premium = _D( '3000' ) )
        self.assertEqual(
            self.engine._premium_tax_credit( self.fpl * _D( '4.1' ), enrollment ), _D( '0' ) )


class PremiumTaxCreditActualCapTest( unittest.TestCase ):
    """The credit cannot exceed the premium of the plan actually held. At 150% FPL the
    benchmark-minus-contribution figure is large (~7k), so it is the actual premium that binds when the
    household holds a cheaper plan; a benchmark-priced plan leaves the credit uncapped."""

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )
        self.magi   = federal_2026().aca.poverty_line( 1 ) * _D( '1.5' )   # 150% FPL, well within range

    def _credit( self, actual_premium ):
        enrollment = SubsidizedHealthEnrollment(
            household_size = 1, reference_premium = _D( '8000' ), actual_premium = _D( actual_premium ) )
        return self.engine._premium_tax_credit( self.magi, enrollment )

    def test_credit_is_capped_at_a_cheaper_actual_premium( self ):
        # The uncapped benchmark-based credit (~7k) exceeds the 5,000 premium paid, so the credit is 5,000.
        self.assertEqual( self._credit( '5000' ), _D( '5000' ) )

    def test_credit_is_uncapped_at_a_benchmark_priced_plan( self ):
        # actual == benchmark, so the cap does not bind: the credit is the (smaller) benchmark-minus-
        # contribution figure, strictly between zero and the premium.
        credit = self._credit( '8000' )
        self.assertGreater( credit, _D( '0' ) )
        self.assertLess( credit, _D( '8000' ) )

    def test_a_cheaper_plan_caps_below_the_benchmark_credit( self ):
        # The same household, benchmark plan vs. a cheaper plan: the cheaper plan's credit is strictly
        # lower -- the cap bit.
        self.assertLess( self._credit( '5000' ), self._credit( '8000' ) )


if __name__ == '__main__':
    unittest.main()
