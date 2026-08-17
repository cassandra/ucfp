"""Unit coverage for the shared expense-totals core (#182): cadence-normalized summing and fragment
rendering. The per-pane assemblies (Vehicle here; Living/Home in later phases) are covered by their own
tests -- this pins the primitives they all build on."""
from decimal import Decimal

from django.test import RequestFactory, SimpleTestCase

from common.recurrence import Duration, TimeUnit

from ucfp.inputs.expense_totals import ExpenseTotal, annualized_sum, rendered

_MONTHLY   = Duration( 1, TimeUnit.MONTH )
_WEEKLY    = Duration( 1, TimeUnit.WEEK )
_YEARLY    = Duration( 1, TimeUnit.YEAR )
_TRIENNIAL = Duration( 3, TimeUnit.YEAR )


class AnnualizedSumTest( SimpleTestCase ):

    def test_normalizes_each_cadence_to_a_yearly_figure( self ):
        # 100/mo -> 1200, 10/wk -> 520, 300/yr -> 300.
        pairs = [ ( Decimal( '100' ), _MONTHLY ), ( Decimal( '10' ), _WEEKLY ), ( Decimal( '300' ), _YEARLY ) ]
        self.assertEqual( annualized_sum( pairs ), Decimal( '2020' ) )

    def test_multi_year_cadence_contributes_a_fractional_year_share( self ):
        # Every third year: a third of the amount each year.
        self.assertEqual( annualized_sum( [ ( Decimal( '300' ), _TRIENNIAL ) ] ), Decimal( '100' ) )

    def test_missing_amount_counts_as_zero( self ):
        self.assertEqual(
            annualized_sum( [ ( None, _MONTHLY ), ( Decimal( '50' ), _MONTHLY ) ] ), Decimal( '600' ) )

    def test_empty_is_zero( self ):
        self.assertEqual( annualized_sum( [] ), Decimal( '0' ) )

    def test_rounds_each_row_to_whole_dollars_before_summing( self ):
        # Each row annualizes to $0.48 and rounds to $0, so the total is $0 (round-then-sum) -- not the
        # $1 a sum-then-round would give. This is the settled rounding rule (matches the calculator readout).
        pairs = [ ( Decimal( '0.04' ), _MONTHLY ), ( Decimal( '0.04' ), _MONTHLY ) ]
        self.assertEqual( annualized_sum( pairs ), Decimal( '0' ) )


class RenderedFragmentsTest( SimpleTestCase ):

    def test_each_total_becomes_an_id_keyed_fragment( self ):
        totals = [ ExpenseTotal( element_id = 'total-a', amount = Decimal( '600' ) ),
                   ExpenseTotal( element_id = 'total-b', amount = Decimal( '0' ) ) ]
        fragments = rendered( RequestFactory().get( '/' ), totals )
        self.assertEqual( set( fragments ), { 'total-a', 'total-b' } )
        self.assertIn( 'id="total-a"', fragments[ 'total-a' ] )      # the replace target the view keys off
        self.assertIn( '600', fragments[ 'total-a' ] )              # the formatted figure
