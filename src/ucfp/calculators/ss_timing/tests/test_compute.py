"""The Social Security claiming-strategy sweep: grid shape, the present-value/raw reduction, and the
survivor step-up as seen through the year-by-year benefit rows.

Each strategy is a full engine run, so these exercise the whole compute core (specialized SS-only
materialization -> engine -> books reduction). Claimants are born January 1 so a claiming age is an
exact date; horizons are kept short to keep an 81-run couple sweep fast.
"""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from common.rate import Rate, ZERO_RATE
from ucfp.calculators.ss_timing import compute as _compute
from ucfp.calculators.ss_timing.compute import (
    Assumptions, Claimant, LifeExpectancyBasis, compare_claiming_strategies, deciding_count, earners_of,
    member_claims, strategy_year_details )
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.forecast.forecast import Forecast
from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.us.mortality import Sex, alive_fraction, life_expectancy

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

    def test_no_return_makes_effective_value_equal_present_value( self ):
        # With no expected return, the effective-value discount coincides with the present-value discount,
        # so the two figures are identical everywhere and the ranking is unchanged from plain PV.
        comparison = compare_claiming_strategies(
            self._solo(), Assumptions.from_inflation( inflation = Rate( Decimal( '0.03' ) ) ) )
        for strategy in comparison.strategies:
            self.assertEqual( strategy.present_value, strategy.effective_value )

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


class SingleEarnerCoupleTest( unittest.TestCase ):
    """A couple with a non-earning spouse (one PIA is zero). The spouse claims a spousal benefit when the
    primary earner files, so the couple's decision collapses to one dimension: 9 strategies over the
    earner's claim age, not the 81-cell grid. The spouse's spousal and survivor benefits still flow, from
    the engine's non-earning-spouse path (a None PIA, not the entered zero)."""

    def _couple( self, higher_life = 84, partner_life = 88 ):
        # The partner has never worked (PIA 0); the earner sorts first regardless of input order.
        return [ Claimant( 'Individual', 1960, Decimal( '3000' ), higher_life ),
                 Claimant( 'Partner', 1960, Decimal( '0' ), partner_life ) ]

    def _rows( self, household, claim_ages, assumptions = _NO_OVERLAY ) -> dict:
        comparison = compare_claiming_strategies( household, assumptions )
        strategy   = next( s for s in comparison.strategies if s.claim_ages == claim_ages )
        return { row.year: row for row in strategy_year_details( comparison.claimants, strategy ) }

    def test_deciding_count_is_one_for_a_non_earning_spouse( self ):
        self.assertEqual( deciding_count( self._couple() ), 1 )                       # one earner decides
        self.assertEqual( deciding_count(
            [ Claimant( 'Higher', 1960, Decimal( '3000' ), 84 ),
              Claimant( 'Lower', 1962, Decimal( '1200' ), 88 ) ] ), 2 )              # dual earners
        self.assertEqual( deciding_count( [ Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ) ] ), 1 )

    def test_the_sweep_collapses_to_the_nine_earner_ages( self ):
        comparison = compare_claiming_strategies( self._couple(), _assumptions() )
        self.assertEqual( len( comparison.strategies ), 9 )                           # not 81
        self.assertTrue( all(
            len( strategy.claim_ages ) == 1 for strategy in comparison.strategies ) )
        self.assertEqual(
            sorted( strategy.claim_ages[ 0 ] for strategy in comparison.strategies ),
            list( range( 62, 71 ) ) )

    def test_the_household_stays_two_people_with_the_earner_first( self ):
        # Even collapsed to one dimension the household keeps both people (for the recap and detail), the
        # positive-PIA earner ordered first whichever way the input was entered.
        reversed_input = [ Claimant( 'Partner', 1960, Decimal( '0' ), 88 ),
                           Claimant( 'Individual', 1960, Decimal( '3000' ), 84 ) ]
        comparison     = compare_claiming_strategies( reversed_input, _assumptions() )
        self.assertEqual( [ c.name for c in comparison.claimants ], [ 'Individual', 'Partner' ] )

    def test_an_all_zero_household_has_no_strategy_to_compare( self ):
        with self.assertRaises( ValueError ):
            compare_claiming_strategies(
                [ Claimant( 'A', 1960, Decimal( '0' ), 84 ),
                  Claimant( 'B', 1960, Decimal( '0' ), 88 ) ], _assumptions() )

    def test_the_non_earning_spouse_claims_a_full_spousal_at_the_earners_fra( self ):
        # Both born 1960 (FRA 67); the earner claims at 67, so the spouse claims spousal that same year at
        # their own FRA -> the full half-PIA, unreduced. Higher own 36,000/yr; spousal 18,000/yr.
        both_alive = self._rows( self._couple(), ( 67, ) )[ 2028 ]
        self.assertEqual( both_alive.members[ 0 ].own, Decimal( '36000' ) )           # earner: own only
        self.assertEqual( both_alive.members[ 1 ].own, Decimal( '0' ) )               # spouse: no own
        self.assertEqual( both_alive.members[ 1 ].spousal, Decimal( '18000' ) )       # half the earner PIA

    def test_the_spousal_benefit_begins_when_the_primary_files_not_at_a_swept_age( self ):
        # The spouse is not swept: whenever the earner claims (here 62, in 2022), the spousal begins that
        # same year -- the one-dimensional, same-time assumption. So a both-alive year right after pays a
        # spousal top-up even though the spouse chose no age of their own.
        early = self._rows( self._couple(), ( 62, ) )[ 2023 ]
        self.assertGreater( early.members[ 1 ].spousal, Decimal( '0' ) )

    def test_the_non_earning_survivor_inherits_the_earners_benefit( self ):
        # The earner dies at 70 (2030); the non-earning spouse survives on the survivor benefit = the
        # earner's own (the spouse's own is zero), replacing their spousal.
        rows          = self._rows( self._couple( higher_life = 70, partner_life = 85 ), ( 67, ) )
        survivor_year = rows[ 2031 ]
        self.assertTrue( survivor_year.is_transition )
        self.assertEqual( survivor_year.members[ 1 ].survivor, Decimal( '36000' ) )   # the earner's own
        self.assertEqual( survivor_year.members[ 1 ].spousal, Decimal( '0' ) )        # spousal ends
        self.assertEqual( survivor_year.members[ 0 ].total, Decimal( '0' ) )          # the decedent

    def test_member_claims_pins_the_spouse_to_the_primary_date_with_no_own_pia( self ):
        earners = earners_of( self._couple() )
        claims  = member_claims( earners, ( 64, ) )
        self.assertTrue( claims[ 0 ].is_earner )
        self.assertEqual( claims[ 0 ].claim_age, 64 )
        self.assertFalse( claims[ 1 ].is_earner )                                     # the non-earning spouse
        self.assertEqual( claims[ 1 ].claiming_date, claims[ 0 ].claiming_date )      # claims with the primary


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


class ActuarialBasisTest( unittest.TestCase ):
    """The ACTUARIAL basis weights each year's benefit by the probability the claimant is alive to receive
    it, over the survival curve to the age-100 cap, and reports the mortality-weighted expected value."""

    def _solo_strategy( self, claim_age, *, basis, life = 100, setback = 0, sex = Sex.MALE,
                        assumptions = None ):
        claimant   = Claimant( 'Solo', 1960, Decimal( '2000' ), life, sex, setback )
        comparison = compare_claiming_strategies(
            [ claimant ], assumptions or _assumptions(), basis )
        return next( s for s in comparison.strategies if s.claim_ages == ( claim_age, ) )

    def test_single_expected_value_matches_a_hand_weighted_survival_sum( self ):
        # With no overlay each claimed year books the same benefit, so the expected lifetime total is that
        # benefit times the sum of the mid-year survival weights -- computed here straight from the survival
        # curve, independently of the engine sweep.
        strategy = self._solo_strategy( 62, basis = LifeExpectancyBasis.ACTUARIAL, assumptions = _NO_OVERLAY )
        pension  = GovernmentPension( JurisdictionType.US_FEDERAL )
        benefit  = pension.realized_annual_benefit(
            Decimal( '2000' ), date( 1960, 1, 1 ), date( 2022, 1, 1 ) )       # claimed at 62
        expected = sum( ( benefit * alive_fraction( 62, age, Sex.MALE ) for age in range( 62, 101 ) ),
                        Decimal( '0' ) )                                       # ages 62..100 (the cap)
        self.assertAlmostEqual( strategy.raw_total, expected, delta = Decimal( '1' ) )

    def test_actuarial_is_below_deterministic_survival_to_the_same_horizon( self ):
        # Same claim, same age-100 horizon: weighting each year by survival can only lower the total against
        # a run in which the claimant is assumed alive (to 100) every year.
        deterministic = self._solo_strategy( 70, basis = LifeExpectancyBasis.SPECIFIC )   # life = 100
        weighted      = self._solo_strategy( 70, basis = LifeExpectancyBasis.ACTUARIAL )
        self.assertLess( weighted.raw_total, deterministic.raw_total )

    def test_a_frailer_setback_lowers_and_a_healthier_one_raises_the_expected_value( self ):
        average  = self._solo_strategy( 67, basis = LifeExpectancyBasis.ACTUARIAL, setback = 0 ).raw_total
        frailer  = self._solo_strategy( 67, basis = LifeExpectancyBasis.ACTUARIAL, setback = 3 ).raw_total
        healthier = self._solo_strategy( 67, basis = LifeExpectancyBasis.ACTUARIAL, setback = -3 ).raw_total
        self.assertLess( frailer, average )
        self.assertGreater( healthier, average )

    def test_the_horizon_runs_to_the_age_100_cap_ignoring_the_expected_lifetime( self ):
        # The entered expected lifetime (80) does not bound the actuarial run: it projects to the age-100 cap
        # (2060 for a 1960 birth) and lets the survival weights taper the tail.
        strategy = self._solo_strategy( 62, basis = LifeExpectancyBasis.ACTUARIAL, life = 80 )
        self.assertEqual( strategy.year_benefits[ -1 ].year, 2060 )

    def _couple( self, higher_setback = 0 ):
        return [ Claimant( 'Higher', 1958, Decimal( '2600' ), 100, Sex.MALE, higher_setback ),
                 Claimant( 'Lower', 1960, Decimal( '1400' ), 100, Sex.FEMALE ) ]

    def test_a_couple_sweep_covers_the_grid_and_holds_the_value_ordering( self ):
        priced     = Assumptions.from_inflation(
            inflation = Rate( Decimal( '0.03' ) ), expected_return = Rate( Decimal( '0.06' ) ) )
        comparison = compare_claiming_strategies(
            self._couple(), priced, LifeExpectancyBasis.ACTUARIAL )
        self.assertEqual( len( comparison.strategies ), 81 )
        for strategy in comparison.strategies:
            self.assertLessEqual( strategy.effective_value, strategy.present_value + Decimal( '0.01' ) )
            self.assertLessEqual( strategy.present_value, strategy.raw_total + Decimal( '0.01' ) )
            self.assertGreater( strategy.raw_total, Decimal( '0' ) )
            continue

    def test_a_frailer_higher_earner_lowers_the_couple_expected_value( self ):
        # A shorter-lived higher earner shifts weight from the both-alive years (two benefits plus the
        # spousal top-up) toward the survivor years (the single inherited benefit), lowering the expectation.
        def household_total( higher_setback ):
            comparison = compare_claiming_strategies(
                self._couple( higher_setback ), _assumptions(), LifeExpectancyBasis.ACTUARIAL )
            return next( s for s in comparison.strategies if s.claim_ages == ( 67, 67 ) ).raw_total
        self.assertLess( household_total( 3 ), household_total( 0 ) )

    def test_no_expected_benefit_before_the_earliest_claim( self ):
        # Regression: the couple survival-state runs placed each death at the horizon start, and the
        # decedent's inherited benefit was ungated -- so the survivor states booked a benefit from year one,
        # giving pre-claim years a spurious expected value. With both claiming at 70, every year before the
        # older earner's age-70 claim must be exactly zero.
        comparison = compare_claiming_strategies(
            self._couple(), _assumptions(), LifeExpectancyBasis.ACTUARIAL )
        strategy            = next( s for s in comparison.strategies if s.claim_ages == ( 70, 70 ) )
        earliest_claim_year = 1958 + 70                                    # the older earner's age-70 claim
        pre_claim           = [ b for b in strategy.year_benefits if b.year < earliest_claim_year ]
        self.assertTrue( pre_claim )                                       # there are pre-claim years
        for benefit in pre_claim:
            self.assertEqual( benefit.nominal, Decimal( '0' ) )

    def test_couple_expected_value_matches_the_weighted_state_streams( self ):
        # The per-year expected nominal must equal the three survival-state runs combined by the joint
        # mid-year survival weights: both*hf*lf + higher-survivor*hf*(1-lf) + lower-survivor*lf*(1-hf).
        # Recompute it independently to catch a state/weight pairing or sign slip in _weighted_couple.
        earners = earners_of( [ Claimant( 'Higher', 1958, Decimal( '3000' ), 100, Sex.MALE ),
                                Claimant( 'Lower', 1960, Decimal( '1200' ), 100, Sex.FEMALE ) ] )
        horizon       = _compute._Horizon.actuarial( earners )
        claim, before = ( 66, 68 ), horizon.start_year - 1

        def state_stream( deaths ):
            return _compute._nominal_by_year(
                _compute._run( earners, claim, _NO_OVERLAY, deaths, horizon ), horizon )

        both, hi_al, lo_al = ( state_stream( [ None, None ] ),
                               state_stream( [ None, before ] ), state_stream( [ before, None ] ) )
        higher, lower = earners
        got           = _compute._weighted_couple( earners, claim, _NO_OVERLAY, horizon )
        for offset, year in enumerate( range( horizon.start_year, horizon.end_year + 1 ) ):
            hf = alive_fraction( horizon.start_year - higher.birth_year, year - higher.birth_year,
                                 higher.sex, higher.setback )
            lf = alive_fraction( horizon.start_year - lower.birth_year, year - lower.birth_year,
                                 lower.sex, lower.setback )
            expected = ( both[ offset ] * ( hf * lf )
                         + hi_al[ offset ] * ( hf * ( 1 - lf ) )
                         + lo_al[ offset ] * ( lf * ( 1 - hf ) ) )
            self.assertEqual( got[ offset ], expected )

    def test_representative_claimants_fill_expected_lifetime_from_the_tables( self ):
        # The recap's reported life expectancy and the year-by-year survivor transition both read these
        # ages, so each must be the mortality table's life_expectancy at that person's earliest-claim age.
        couple = [ Claimant( 'Higher', 1958, Decimal( '3000' ), None, Sex.MALE ),
                   Claimant( 'Lower', 1960, Decimal( '1200' ), None, Sex.FEMALE ) ]
        reps  = _compute.representative_claimants( couple )
        self.assertEqual( [ rep.name for rep in reps ], [ 'Higher', 'Lower' ] )      # higher earner first
        start = min( claimant.birth_year + 62 for claimant in couple )               # earliest age-62 claim
        for rep in reps:
            self.assertEqual( rep.expected_lifetime,
                              round( life_expectancy( start - rep.birth_year, rep.sex, rep.setback ) ) )
        preset = _compute.representative_claimants( [ replace( couple[ 0 ], expected_lifetime = 999 ) ] )
        self.assertNotEqual( preset[ 0 ].expected_lifetime, 999 )                    # recomputed, not kept

    def test_the_specific_basis_is_the_default( self ):
        # The default basis is SPECIFIC (the exact deterministic path); ACTUARIAL is opt-in.
        solo    = [ Claimant( 'Solo', 1960, Decimal( '2000' ), 100, Sex.MALE ) ]
        default = compare_claiming_strategies( solo, _assumptions() )
        chosen  = compare_claiming_strategies( solo, _assumptions(), LifeExpectancyBasis.SPECIFIC )
        self.assertEqual( default.best.raw_total, chosen.best.raw_total )


def _income_tax_booked( result, through ) -> Decimal:
    """The income tax the run booked through `through` -- summed across the income-tax expense accounts."""
    reader = Bookkeeper( result.books )
    return sum( ( reader.ledger.natural_balance( account, through = through )
                  for account in result.books.accounts if 'Income Tax' in account.name ),
                Decimal( '0' ) )


class SkipTaxationTest( unittest.TestCase ):
    """The SS-only run skips the tax layer for speed. Since the comparison ranks by gross booked Social
    Security -- which taxation never changes -- the benefit stream must be identical with tax skipped."""

    def test_skipping_taxation_preserves_social_security_when_tax_actually_applies( self ):
        # A high-PIA couple genuinely incurs income tax, so this is not a no-tax no-op: the taxed run books
        # real income tax and the skipped run books none, yet the gross Social Security stream is identical.
        earners = earners_of( [ Claimant( 'Higher', 1958, Decimal( '8000' ), 90 ),
                                Claimant( 'Lower', 1960, Decimal( '8000' ), 90 ) ] )
        horizon = _compute._Horizon.for_household( earners )
        through = date( horizon.end_year, 12, 31 )
        deaths  = [ earner.birth_year + earner.expected_lifetime for earner in earners ]
        skipped = _compute._forecast_parameters( earners, ( 67, 67 ), _assumptions(), deaths, horizon )
        self.assertTrue( skipped.skip_taxation )                            # the SS calculator sets it
        taxed   = replace( skipped, skip_taxation = False )
        skipped_run, taxed_run = Forecast( skipped ).run(), Forecast( taxed ).run()
        self.assertGreater( _income_tax_booked( taxed_run, through ), Decimal( '0' ) )   # taxed path taxes
        self.assertEqual( _income_tax_booked( skipped_run, through ), Decimal( '0' ) )   # skipped books none
        self.assertEqual( _compute._nominal_by_year( skipped_run, horizon ),             # SS identical
                          _compute._nominal_by_year( taxed_run, horizon ) )


if __name__ == '__main__':
    unittest.main()
