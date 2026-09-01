"""The Social Security claiming-strategy sweep: grid shape, the present-value/raw reduction, and the
survivor step-up as seen through the year-by-year benefit rows.

Each strategy is a full engine run, so these exercise the whole compute core (specialized SS-only
materialization -> engine -> books reduction). Claimants are born January 1 so a claiming age is an
exact date; horizons are kept short to keep an 81-run couple sweep fast.
"""
import unittest
from decimal import Decimal

from common.rate import Rate
from ucfp.planning.ss_timing import Assumptions, Claimant, compare_claiming_strategies


def _assumptions( inflation = '0.03', cola = '0.02' ) -> Assumptions:
    return Assumptions( inflation = Rate( Decimal( inflation ) ), cola = Rate( Decimal( cola ) ) )


def _year_map( strategy ) -> dict:
    """The strategy's nominal Social Security keyed by year -- for asserting the shape of the arc."""
    return { benefit.year: benefit.nominal for benefit in strategy.year_benefits }


class ClaimingSweepShapeTest( unittest.TestCase ):

    def test_a_couple_sweeps_the_full_nine_by_nine_grid( self ):
        couple = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 78 ),
                   Claimant( 'Lower', 1962, Decimal( '1200' ), 80 ) ]
        comparison = compare_claiming_strategies( couple, _assumptions() )
        self.assertEqual( len( comparison.strategies ), 81 )
        self.assertTrue( all(
            len( strategy.claim_ages ) == 2 for strategy in comparison.strategies ) )
        self.assertTrue( all(
            62 <= age <= 70 for strategy in comparison.strategies for age in strategy.claim_ages ) )

    def test_claimants_are_ordered_higher_earner_first( self ):
        # Input order is lower-then-higher; the comparison reorders by PIA (the grid's orientation).
        couple     = [ Claimant( 'Lower', 1962, Decimal( '1200' ), 80 ),
                       Claimant( 'Higher', 1960, Decimal( '3000' ), 78 ) ]
        comparison = compare_claiming_strategies( couple, _assumptions() )
        self.assertEqual( [ claimant.name for claimant in comparison.claimants ], [ 'Higher', 'Lower' ] )

    def test_a_single_person_sweeps_nine_ages( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ], _assumptions() )
        self.assertEqual( len( comparison.strategies ), 9 )
        self.assertEqual(
            sorted( strategy.claim_ages[ 0 ] for strategy in comparison.strategies ),
            list( range( 62, 71 ) ) )

    def test_a_household_must_be_one_person_or_a_couple( self ):
        with self.assertRaises( ValueError ):
            compare_claiming_strategies( [], _assumptions() )


class ClaimingSweepReductionTest( unittest.TestCase ):

    def test_year_benefits_sum_to_the_raw_and_present_value_totals( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ], _assumptions() )
        for strategy in comparison.strategies:
            raw = sum( ( benefit.nominal for benefit in strategy.year_benefits ), Decimal( '0' ) )
            pv  = sum( ( benefit.present_value for benefit in strategy.year_benefits ), Decimal( '0' ) )
            self.assertEqual( strategy.raw_total, raw )
            self.assertEqual( strategy.present_value, pv )

    def test_present_value_does_not_exceed_the_raw_total_under_inflation( self ):
        # A positive inflation discount makes each year's present value <= its nominal, so the totals do too.
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ], _assumptions( inflation = '0.03' ) )
        for strategy in comparison.strategies:
            self.assertLessEqual( strategy.present_value, strategy.raw_total )

    def test_best_is_the_highest_present_value_and_ranked_is_descending( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 95 ) ], _assumptions() )
        self.assertEqual(
            comparison.best.present_value,
            max( strategy.present_value for strategy in comparison.strategies ) )
        present_values = [ strategy.present_value for strategy in comparison.ranked ]
        self.assertEqual( present_values, sorted( present_values, reverse = True ) )


class ClaimingSweepSurvivorTest( unittest.TestCase ):
    """The survivor step-up (a couple, one dying mid-horizon) shows up in the year rows and responds
    to when the higher earner claimed."""

    def _strategy( self, comparison, higher_age, lower_age ):
        return next( strategy for strategy in comparison.strategies
                     if strategy.claim_ages == ( higher_age, lower_age ) )

    def test_household_benefit_drops_to_the_survivor_after_the_first_death( self ):
        # Higher earner dies at 70 (2030), the lower lives to 85: the household drops from two benefits
        # to the single survivor benefit, which stays positive.
        couple     = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 70 ),
                       Claimant( 'Lower', 1960, Decimal( '1200' ), 85 ) ]
        comparison = compare_claiming_strategies( couple, _assumptions() )
        years      = _year_map( self._strategy( comparison, 67, 67 ) )
        self.assertGreater( years[ 2030 ], years[ 2031 ] )                 # both alive -> survivor only
        self.assertGreater( years[ 2031 ], Decimal( '0' ) )               # survivor keeps collecting
        self.assertLess( years[ 2031 ], years[ 2030 ] * Decimal( '0.8' ) )  # a real drop, not just the COLA

    def test_delaying_the_higher_earner_raises_the_survivor_benefit( self ):
        # After the higher earner's death the survivor inherits the higher earner's own benefit, which
        # is larger when claimed at 70 than at 62 -- so a post-death year pays more under the delay.
        couple      = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 70 ),
                        Claimant( 'Lower', 1960, Decimal( '1200' ), 85 ) ]
        comparison  = compare_claiming_strategies( couple, _assumptions() )
        claimed_early = _year_map( self._strategy( comparison, 62, 67 ) )
        claimed_late  = _year_map( self._strategy( comparison, 70, 67 ) )
        self.assertGreater( claimed_late[ 2032 ], claimed_early[ 2032 ] )


if __name__ == '__main__':
    unittest.main()
