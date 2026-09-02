"""The Social Security claiming-strategy sweep: grid shape, the present-value/raw reduction, and the
survivor step-up as seen through the year-by-year benefit rows.

Each strategy is a full engine run, so these exercise the whole compute core (specialized SS-only
materialization -> engine -> books reduction). Claimants are born January 1 so a claiming age is an
exact date; horizons are kept short to keep an 81-run couple sweep fast.
"""
import unittest
from decimal import Decimal

from common.rate import Rate, ZERO_RATE
from ucfp.calculators.ss_timing.compute import (
    Assumptions, Claimant, compare_claiming_strategies, strategy_year_details )

_NO_OVERLAY = Assumptions( inflation = ZERO_RATE, cola = ZERO_RATE )


def _assumptions( inflation = '0.03', cola = '0.02' ) -> Assumptions:
    return Assumptions( inflation = Rate( Decimal( inflation ) ), cola = Rate( Decimal( cola ) ) )


def _year_map( strategy ) -> dict:
    """The strategy's nominal Social Security keyed by year -- for asserting the shape of the arc."""
    return { benefit.year: benefit.nominal for benefit in strategy.year_benefits }


class AssumptionsFromInflationTest( unittest.TestCase ):
    """`Assumptions.from_inflation` derives the SS cost-of-living adjustment as inflation less a fixed lag,
    floored at zero so a low inflation rate never feeds the engine a negative COLA."""

    def test_the_cola_is_inflation_less_the_lag( self ):
        assumptions = Assumptions.from_inflation( inflation = Rate( Decimal( '0.025' ) ) )
        self.assertEqual( assumptions.cola, Rate( Decimal( '0.022' ) ) )          # 2.5% - 0.3%

    def test_the_cola_floors_at_zero_below_the_lag( self ):
        self.assertEqual( Assumptions.from_inflation( inflation = ZERO_RATE ).cola, ZERO_RATE )
        below_lag = Assumptions.from_inflation( inflation = Rate( Decimal( '0.001' ) ) )   # under the lag
        self.assertEqual( below_lag.cola, ZERO_RATE )                             # floored, not negative


class OpportunityCostDiscountTest( unittest.TestCase ):
    """Present value discounts at the visitor's expected asset return when given -- pricing in the
    opportunity cost of deferring benefits -- else at inflation. A higher discount weighs earlier benefits
    more, so it pulls the best claiming age earlier without collapsing to a corner."""

    def _solo( self, life = 90 ) -> list:
        return [ Claimant( 'Solo', 1960, Decimal( '2000' ), life ) ]

    def test_the_discount_rate_is_the_expected_return_else_inflation( self ):
        inflation = Rate( Decimal( '0.03' ) )
        self.assertEqual( Assumptions( inflation = inflation, cola = ZERO_RATE ).discount_rate, inflation )
        with_return = Assumptions( inflation = inflation, cola = ZERO_RATE,
                                   expected_return = Rate( Decimal( '0.06' ) ) )
        self.assertEqual( with_return.discount_rate, Rate( Decimal( '0.06' ) ) )

    def test_a_higher_expected_return_lowers_a_deferred_strategy_effective_value( self ):
        base = compare_claiming_strategies(
            self._solo(), Assumptions.from_inflation( inflation = Rate( Decimal( '0.03' ) ) ) )
        priced = compare_claiming_strategies( self._solo(), Assumptions.from_inflation(
            inflation = Rate( Decimal( '0.03' ) ), expected_return = Rate( Decimal( '0.08' ) ) ) )
        claim_70_base   = next( s for s in base.strategies if s.claim_ages == ( 70, ) )
        claim_70_priced = next( s for s in priced.strategies if s.claim_ages == ( 70, ) )
        self.assertEqual( claim_70_base.raw_total, claim_70_priced.raw_total )       # same nominal ...
        self.assertEqual( claim_70_base.present_value, claim_70_priced.present_value )   # ... same today's $
        self.assertLess(                                                            # ... but lower effective
            claim_70_priced.effective_value, claim_70_base.effective_value )

    def test_an_expected_return_of_inflation_leaves_the_best_unchanged( self ):
        # Setting the expected return equal to inflation is the zero-real-opportunity-cost view -- identical
        # to leaving it unset, so the recommended age does not move.
        inflation = Rate( Decimal( '0.03' ) )
        unset = compare_claiming_strategies(
            self._solo(), Assumptions.from_inflation( inflation = inflation ) )
        equal = compare_claiming_strategies(
            self._solo(),
            Assumptions.from_inflation( inflation = inflation, expected_return = inflation ) )
        self.assertEqual( equal.best.claim_ages, unset.best.claim_ages )

    def test_a_high_expected_return_moves_the_best_claim_age_earlier( self ):
        inflation_only = compare_claiming_strategies(
            self._solo(), Assumptions.from_inflation( inflation = Rate( Decimal( '0.03' ) ) ) )
        opportunity    = compare_claiming_strategies( self._solo(), Assumptions.from_inflation(
            inflation = Rate( Decimal( '0.03' ) ), expected_return = Rate( Decimal( '0.08' ) ) ) )
        self.assertLess( opportunity.best.claim_ages[ 0 ], inflation_only.best.claim_ages[ 0 ] )

    def test_a_moderate_return_gives_an_interior_best_not_a_corner( self ):
        # A middling real return (~3%) with average longevity optimizes to an age strictly inside 62..70 --
        # the opportunity cost shaves the delay rather than collapsing to "claim as early as possible".
        comparison = compare_claiming_strategies( self._solo( life = 86 ), Assumptions.from_inflation(
            inflation = Rate( Decimal( '0.025' ) ), expected_return = Rate( Decimal( '0.055' ) ) ) )
        best_age = comparison.best.claim_ages[ 0 ]
        self.assertGreater( best_age, 62 )
        self.assertLess( best_age, 70 )


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

    def test_year_benefits_sum_to_the_lifetime_totals( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ], _assumptions() )
        for strategy in comparison.strategies:
            raw = sum( ( benefit.nominal for benefit in strategy.year_benefits ), Decimal( '0' ) )
            pv  = sum( ( benefit.present_value for benefit in strategy.year_benefits ), Decimal( '0' ) )
            ev  = sum( ( benefit.effective_value for benefit in strategy.year_benefits ), Decimal( '0' ) )
            self.assertEqual( strategy.raw_total, raw )
            self.assertEqual( strategy.present_value, pv )
            self.assertEqual( strategy.effective_value, ev )

    def test_present_value_does_not_exceed_the_raw_total_under_inflation( self ):
        # A positive inflation discount makes each year's present value <= its nominal, so the totals do too.
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ], _assumptions( inflation = '0.03' ) )
        for strategy in comparison.strategies:
            self.assertLessEqual( strategy.present_value, strategy.raw_total )

    def test_best_is_the_highest_effective_value_and_ranked_is_descending( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 95 ) ], _assumptions() )
        self.assertEqual(
            comparison.best.effective_value,
            max( strategy.effective_value for strategy in comparison.strategies ) )
        effective_values = [ strategy.effective_value for strategy in comparison.ranked ]
        self.assertEqual( effective_values, sorted( effective_values, reverse = True ) )


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


class StrategyDetailTest( unittest.TestCase ):
    """The year-by-year drill-in: each year's engine household total apportioned into the members' own /
    spousal / survivor parts (higher earner first). With no overlay the nominal parts equal the today's
    statutory amounts, so they can be asserted directly."""

    def _rows( self, household, assumptions, claim_ages ) -> dict:
        comparison = compare_claiming_strategies( household, assumptions )
        strategy   = next( s for s in comparison.strategies if s.claim_ages == claim_ages )
        return { row.year: row for row in strategy_year_details( comparison.claimants, strategy ) }

    def test_the_parts_reconcile_to_the_engine_household_total_each_year( self ):
        # Under a real overlay (COLA + reduction) the apportioned parts reconcile to the engine total, to
        # within its per-posting cent rounding -- the split is exact in ratio, the total stays the engine's.
        couple      = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 72 ),
                        Claimant( 'Lower', 1962, Decimal( '1200' ), 84 ) ]
        assumptions = Assumptions(
            inflation = Rate( Decimal( '0.03' ) ), cola = Rate( Decimal( '0.02' ) ),
            benefits_payable = Rate( Decimal( '0.80' ) ), reduction_year = 2034 )
        for row in self._rows( couple, assumptions, ( 67, 67 ) ).values():
            parts = sum( ( member.total for member in row.members ), Decimal( '0' ) )
            self.assertLess( abs( parts - row.household ), Decimal( '0.05' ) )

    def test_a_both_alive_year_splits_into_own_and_the_lower_spousal( self ):
        couple     = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 72 ),
                       Claimant( 'Lower', 1960, Decimal( '1000' ), 84 ) ]
        both_alive = self._rows( couple, _NO_OVERLAY, ( 67, 67 ) )[ 2028 ]
        self.assertEqual( both_alive.ages, ( 68, 68 ) )
        self.assertEqual( both_alive.members[ 0 ].own, Decimal( '36000' ) )      # higher: own only
        self.assertEqual( both_alive.members[ 0 ].spousal, Decimal( '0' ) )
        self.assertEqual( both_alive.members[ 1 ].own, Decimal( '12000' ) )      # lower: own
        self.assertEqual( both_alive.members[ 1 ].spousal, Decimal( '6000' ) )   # + spousal excess

    def test_the_survivor_year_is_flagged_and_carries_the_survivor_part( self ):
        couple = [ Claimant( 'Higher', 1960, Decimal( '3000' ), 70 ),            # dies 2030
                   Claimant( 'Lower', 1960, Decimal( '1000' ), 85 ) ]
        rows   = self._rows( couple, _NO_OVERLAY, ( 67, 67 ) )
        survivor_year = rows[ 2031 ]
        self.assertTrue( survivor_year.is_transition )                          # the first survivor year
        self.assertEqual( survivor_year.members[ 1 ].survivor, Decimal( '36000' ) )
        self.assertEqual( survivor_year.members[ 1 ].own, Decimal( '0' ) )
        self.assertEqual( survivor_year.members[ 0 ].total, Decimal( '0' ) )    # the decedent
        self.assertFalse( rows[ 2032 ].is_transition )                         # only the first is flagged

    def test_a_single_person_detail_has_one_own_only_member( self ):
        comparison = compare_claiming_strategies(
            [ Claimant( 'Solo', 1960, Decimal( '2000' ), 80 ) ], _NO_OVERLAY )
        strategy = next( s for s in comparison.strategies if s.claim_ages == ( 67, ) )
        rows     = { row.year: row for row in strategy_year_details( comparison.claimants, strategy ) }
        self.assertEqual( len( rows[ 2028 ].members ), 1 )
        self.assertEqual( rows[ 2028 ].members[ 0 ].own, Decimal( '24000' ) )   # 2000 * 12
        self.assertFalse( any( row.is_transition for row in rows.values() ) )   # no survivor for one person


if __name__ == '__main__':
    unittest.main()
