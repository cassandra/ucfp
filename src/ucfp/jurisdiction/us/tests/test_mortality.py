"""Conditional survival math (`ucfp.jurisdiction.us.mortality`). The math is exercised against a small
synthetic life table so the functions are trustworthy independently of the real data; the bundled SSA
table is then checked for well-formedness, against its own published life-expectancy column, and against
an independent source (the CDC/NCHS 2024 US life tables) as a same-ballpark guard (#250).
"""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.us.mortality import (
    SSA_DEATH_PROBABILITY, Sex, alive_fraction, life_expectancy, survival_probability )

# A synthetic table: male mortality above female, doubling each year, everyone gone by 64. Chosen so the
# survival products are exact, short Decimals.
_TABLE = {
    60: ( 0.02, 0.01 ),
    61: ( 0.04, 0.02 ),
    62: ( 0.08, 0.04 ),
    63: ( 0.16, 0.08 ),
    64: ( 1.00, 1.00 ),
}


class SurvivalProbabilityTest( unittest.TestCase ):

    def test_survival_to_the_current_age_or_earlier_is_certain( self ):
        self.assertEqual( survival_probability( 60, 60, Sex.MALE, table = _TABLE ), Decimal( '1' ) )
        self.assertEqual( survival_probability( 60, 59, Sex.MALE, table = _TABLE ), Decimal( '1' ) )

    def test_survival_is_the_running_product_of_one_minus_qx( self ):
        self.assertEqual( survival_probability( 60, 61, Sex.MALE, table = _TABLE ), Decimal( '0.98' ) )
        self.assertEqual( survival_probability( 60, 62, Sex.MALE, table = _TABLE ), Decimal( '0.9408' ) )

    def test_male_survival_is_below_female_at_the_same_age( self ):
        male   = survival_probability( 60, 62, Sex.MALE, table = _TABLE )
        female = survival_probability( 60, 62, Sex.FEMALE, table = _TABLE )
        self.assertLess( male, female )

    def test_unset_sex_blends_the_two_curves_evenly( self ):
        male    = survival_probability( 60, 62, Sex.MALE, table = _TABLE )
        female  = survival_probability( 60, 62, Sex.FEMALE, table = _TABLE )
        blended = survival_probability( 60, 62, None, table = _TABLE )
        self.assertEqual( blended, ( male + female ) / 2 )

    def test_a_positive_setback_lowers_survival_a_negative_one_raises_it( self ):
        average = survival_probability( 60, 61, Sex.MALE, setback_years = 0, table = _TABLE )
        frailer = survival_probability( 60, 61, Sex.MALE, setback_years = 1, table = _TABLE )
        self.assertEqual( frailer, Decimal( '0.96' ) )              # uses age-61 qx (0.04)
        self.assertLess( frailer, average )
        healthier = survival_probability( 60, 61, Sex.MALE, setback_years = -1, table = _TABLE )
        self.assertGreaterEqual( healthier, average )              # clamps at the youngest row here

    def test_survival_past_the_table_is_zero( self ):
        self.assertEqual( survival_probability( 60, 65, Sex.MALE, table = _TABLE ), Decimal( '0' ) )
        self.assertEqual( survival_probability( 60, 80, Sex.FEMALE, table = _TABLE ), Decimal( '0' ) )


class AliveFractionTest( unittest.TestCase ):

    def test_a_fully_survived_year_counts_about_full_the_death_year_about_half( self ):
        # mid-year convention: weight = (S(start) + S(start+1)) / 2.
        start = survival_probability( 60, 61, Sex.MALE, table = _TABLE )
        end   = survival_probability( 60, 62, Sex.MALE, table = _TABLE )
        self.assertEqual( alive_fraction( 60, 61, Sex.MALE, table = _TABLE ), ( start + end ) / 2 )

    def test_the_final_year_is_half_the_survival_into_it( self ):
        into_it = survival_probability( 60, 64, Sex.MALE, table = _TABLE )   # everyone dies during age 64
        self.assertEqual( alive_fraction( 60, 64, Sex.MALE, table = _TABLE ), into_it / 2 )


class LifeExpectancyTest( unittest.TestCase ):

    def test_it_exceeds_the_current_age_and_responds_to_the_setback( self ):
        average   = life_expectancy( 60, Sex.MALE, setback_years = 0, table = _TABLE )
        self.assertGreater( average, Decimal( '60' ) )
        frailer   = life_expectancy( 60, Sex.MALE, setback_years = 1, table = _TABLE )
        self.assertLess( frailer, average )                        # a shorter expected life

    def test_female_life_expectancy_exceeds_male( self ):
        self.assertGreater(
            life_expectancy( 60, Sex.FEMALE, table = _TABLE ),
            life_expectancy( 60, Sex.MALE, table = _TABLE ) )


class SsaDataTest( unittest.TestCase ):
    """The bundled SSA table itself: shape, well-formedness, and -- the strong checks -- that our
    `life_expectancy` reproduces the SSA table's own published life-expectancy column (validating the
    transcription and the survival math together against the source), and that the resulting expectancies
    sit in the same ballpark as an independent source (CDC/NCHS)."""

    def test_the_table_covers_every_age_zero_through_119( self ):
        self.assertEqual( sorted( SSA_DEATH_PROBABILITY ), list( range( 0, 120 ) ) )

    def test_every_death_probability_is_a_valid_probability( self ):
        for male, female in SSA_DEATH_PROBABILITY.values():
            self.assertTrue( 0 < male <= 1 )
            self.assertTrue( 0 < female <= 1 )

    def test_death_probability_rises_with_age_through_the_lifespan( self ):
        for age in range( 40, 119 ):
            self.assertLessEqual( SSA_DEATH_PROBABILITY[ age ][ 0 ], SSA_DEATH_PROBABILITY[ age + 1 ][ 0 ] )
            self.assertLessEqual( SSA_DEATH_PROBABILITY[ age ][ 1 ], SSA_DEATH_PROBABILITY[ age + 1 ][ 1 ] )

    def test_life_expectancy_reproduces_the_ssa_published_column( self ):
        # The SSA table's own life-expectancy column, as age at death (age + e). Drift from these means
        # either a mis-transcribed row or a bug in the survival math -- the transcription's tripwire.
        published = {
            0  : ( Decimal( '75.79' ), Decimal( '81.06' ) ),
            62 : ( Decimal( '82.29' ), Decimal( '85.08' ) ),
            67 : ( Decimal( '83.71' ), Decimal( '86.08' ) ),
            70 : ( Decimal( '84.66' ), Decimal( '86.76' ) ),
        }
        for age, ( male_age, female_age ) in published.items():
            self.assertAlmostEqual( life_expectancy( age, Sex.MALE ), male_age, delta = Decimal( '0.05' ) )
            self.assertAlmostEqual(
                life_expectancy( age, Sex.FEMALE ), female_age, delta = Decimal( '0.05' ) )

    def test_expectancy_agrees_with_the_cdc_life_tables_in_the_ballpark( self ):
        # Independent cross-source guard: CDC/NCHS 2024 "All origins" remaining expectancy (e_x, years). A
        # different agency, method, and data year, so this is a same-ballpark check (within a year), not an
        # equality. The SSA period basis runs slightly conservative, which is the expected direction.
        cdc_remaining = {                                    # age : ( male e_x, female e_x )
            0  : ( Decimal( '76.5' ), Decimal( '81.4' ) ),
            60 : ( Decimal( '22.1' ), Decimal( '24.9' ) ),
            65 : ( Decimal( '18.4' ), Decimal( '20.8' ) ),
            70 : ( Decimal( '14.9' ), Decimal( '16.9' ) ),
        }
        for age, ( male_ex, female_ex ) in cdc_remaining.items():
            ssa_male   = life_expectancy( age, Sex.MALE ) - age
            ssa_female = life_expectancy( age, Sex.FEMALE ) - age
            self.assertAlmostEqual( ssa_male, male_ex, delta = Decimal( '1.0' ) )
            self.assertAlmostEqual( ssa_female, female_ex, delta = Decimal( '1.0' ) )


if __name__ == '__main__':
    unittest.main()
