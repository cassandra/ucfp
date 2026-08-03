"""Splitting a rental disposition's gain into §1250 recapture and its long-term remainder (#115).

The unrecaptured §1250 gain is the accumulated depreciation, but capped at the actual total gain
(book gain + recapture) -- so a rental sold at or below its adjusted basis recaptures less, or none,
rather than over-recapturing the full accumulation. Exercises `_split_rental_gain` directly."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D = Decimal


class RentalGainSplitTests( unittest.TestCase ):

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )

    def _split( self, book_gain, recapture ):
        return self.engine._split_rental_gain( _D( book_gain ), _D( recapture ) )

    def test_appreciation_recaptures_the_full_depreciation( self ):
        # Sold above cost: total 350k > 150k depreciation, so all 150k recaptures and the 200k
        # appreciation stays long-term (the pre-existing, non-edge behavior).
        split = self._split( '200000', '150000' )
        self.assertEqual( ( split.section_1250, split.long_term ), ( _D( '150000' ), _D( '200000' ) ) )

    def test_sold_below_cost_caps_recapture_at_the_total_gain( self ):
        # Sold 50k below cost after 150k depreciation: total gain is 100k, so recapture is capped at
        # 100k (not the full 150k) and nothing is left long-term -- the over-recapture this fixes.
        split = self._split( '-50000', '150000' )
        self.assertEqual( ( split.section_1250, split.long_term ), ( _D( '100000' ), _D( '0' ) ) )

    def test_sold_below_adjusted_basis_recaptures_nothing_and_leaves_a_loss( self ):
        # Sold so far below cost that the total gain is negative: no recapture, and the loss stays
        # long-term.
        split = self._split( '-200000', '150000' )
        self.assertEqual( ( split.section_1250, split.long_term ), ( _D( '0' ), _D( '-50000' ) ) )

    def test_never_depreciated_rental_has_no_recapture( self ):
        split = self._split( '200000', '0' )
        self.assertEqual( ( split.section_1250, split.long_term ), ( _D( '0' ), _D( '200000' ) ) )


if __name__ == '__main__':
    unittest.main()
