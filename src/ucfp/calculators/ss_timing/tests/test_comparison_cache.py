"""The process-local claiming-sweep cache: identical inputs are served from one memoized `Comparison`, and
the key distinguishes what actually changes the result (the basis) while ignoring input order."""
import unittest
from decimal import Decimal

from common.rate import Rate
from ucfp.calculators.ss_timing.comparison_cache import cached_comparison, clear_comparison_cache
from ucfp.calculators.ss_timing.compute import Assumptions, Claimant, LifeExpectancyBasis


def _assumptions() -> Assumptions:
    return Assumptions.from_inflation( inflation = Rate( Decimal( '0.03' ) ) )


def _couple() -> list:
    return [ Claimant( 'Higher', 1958, Decimal( '2600' ), 90 ),
             Claimant( 'Lower', 1960, Decimal( '1400' ), 92 ) ]


class ComparisonCacheTest( unittest.TestCase ):

    def setUp( self ):
        clear_comparison_cache()

    def tearDown( self ):
        clear_comparison_cache()

    def test_a_repeat_sweep_returns_the_same_memoized_result( self ):
        first  = cached_comparison( _couple(), _assumptions() )
        second = cached_comparison( _couple(), _assumptions() )
        self.assertIs( first, second )                          # a hit, not a recompute

    def test_the_input_order_of_a_couple_shares_one_entry( self ):
        # The key is the PIA-ordered earners, so lower-then-higher and higher-then-lower are one entry.
        higher, lower = _couple()
        self.assertIs(
            cached_comparison( [ higher, lower ], _assumptions() ),
            cached_comparison( [ lower, higher ], _assumptions() ) )

    def test_a_different_basis_is_a_separate_entry( self ):
        specific  = cached_comparison( _couple(), _assumptions(), LifeExpectancyBasis.SPECIFIC )
        actuarial = cached_comparison( _couple(), _assumptions(), LifeExpectancyBasis.ACTUARIAL )
        self.assertIsNot( specific, actuarial )

    def test_clearing_forces_a_recompute( self ):
        first = cached_comparison( _couple(), _assumptions() )
        clear_comparison_cache()
        self.assertIsNot( first, cached_comparison( _couple(), _assumptions() ) )


if __name__ == '__main__':
    unittest.main()
