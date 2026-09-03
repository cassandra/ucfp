"""The country-agnostic bracket table: cumulative tax, and the marginal-rate / bracket-ceiling accessors the
tax display worksheet reads for marginal rates and bracket headroom."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.brackets import BracketTable


def _table() -> BracketTable:
    # A simplified four-bracket schedule (bounds, marginal rate), ascending.
    return BracketTable( (
        ( Decimal( '0' ), Decimal( '0.10' ) ),
        ( Decimal( '10000' ), Decimal( '0.12' ) ),
        ( Decimal( '40000' ), Decimal( '0.22' ) ),
        ( Decimal( '100000' ), Decimal( '0.24' ) ) ) )


class TaxOnTest( unittest.TestCase ):

    def test_cumulative_tax_spans_the_brackets( self ):
        # 10000 @ 10% + 30000 @ 12% + 10000 @ 22% = 1000 + 3600 + 2200.
        self.assertEqual( _table().tax_on( Decimal( '50000' ) ), Decimal( '6800' ) )

    def test_no_income_is_no_tax( self ):
        self.assertEqual( _table().tax_on( Decimal( '0' ) ), Decimal( '0' ) )


class MarginalRateTest( unittest.TestCase ):

    def test_within_a_bracket_takes_that_rate( self ):
        self.assertEqual( _table().marginal_rate( Decimal( '5000' ) ), Decimal( '0.10' ) )
        self.assertEqual( _table().marginal_rate( Decimal( '50000' ) ), Decimal( '0.22' ) )

    def test_a_bound_belongs_to_the_bracket_it_opens( self ):
        # A bound is the first dollar of its bracket, so sitting exactly on it takes the higher rate.
        self.assertEqual( _table().marginal_rate( Decimal( '10000' ) ), Decimal( '0.12' ) )
        self.assertEqual( _table().marginal_rate( Decimal( '40000' ) ), Decimal( '0.22' ) )

    def test_above_the_top_bound_takes_the_top_rate( self ):
        self.assertEqual( _table().marginal_rate( Decimal( '250000' ) ), Decimal( '0.24' ) )

    def test_below_the_first_bound_is_zero( self ):
        offset = BracketTable( ( ( Decimal( '1000' ), Decimal( '0.10' ) ), ) )
        self.assertEqual( offset.marginal_rate( Decimal( '500' ) ), Decimal( '0' ) )

    def test_an_empty_table_is_zero( self ):
        self.assertEqual( BracketTable( () ).marginal_rate( Decimal( '5000' ) ), Decimal( '0' ) )


class CeilingTest( unittest.TestCase ):

    def test_the_ceiling_is_the_next_bound_up( self ):
        self.assertEqual( _table().ceiling( Decimal( '5000' ) ), Decimal( '10000' ) )
        self.assertEqual( _table().ceiling( Decimal( '50000' ) ), Decimal( '100000' ) )

    def test_headroom_is_the_ceiling_less_the_amount( self ):
        amount  = Decimal( '38000' )
        ceiling = _table().ceiling( amount )
        self.assertEqual( ceiling - amount, Decimal( '2000' ) )        # room left in the 12% bracket

    def test_on_a_bound_the_ceiling_is_the_next_one_not_itself( self ):
        self.assertEqual( _table().ceiling( Decimal( '10000' ) ), Decimal( '40000' ) )

    def test_the_top_bracket_has_no_ceiling( self ):
        self.assertIsNone( _table().ceiling( Decimal( '250000' ) ) )

    def test_an_empty_table_has_no_ceiling( self ):
        self.assertIsNone( BracketTable( () ).ceiling( Decimal( '5000' ) ) )


class IndexedTest( unittest.TestCase ):

    def test_indexing_scales_the_bounds_the_accessors_read( self ):
        # After a 10% indexing the 12% bracket opens at 11000, so 10500 is still in the 10% bracket.
        indexed = _table().indexed( Decimal( '1.1' ) )
        self.assertEqual( indexed.marginal_rate( Decimal( '10500' ) ), Decimal( '0.10' ) )
        self.assertEqual( indexed.ceiling( Decimal( '10500' ) ), Decimal( '11000' ) )


if __name__ == '__main__':
    unittest.main()
