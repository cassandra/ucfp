"""The ACA premium tax credit (#114): the 400%-of-FPL eligibility cliff. Exercises
`_premium_tax_credit` directly with a controlled MAGI and enrollment, so the boundary behavior is
isolated from the surrounding income tax it offsets."""
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
        # Household of one: FPL 15,650, so the 400% cliff sits at 62,600 of MAGI.
        self.enrollment = SubsidizedHealthEnrollment( household_size = 1, reference_premium = _D( '8000' ) )
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


if __name__ == '__main__':
    unittest.main()
