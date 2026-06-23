"""Validity gate for the granularity profile matrix: every profile x tier x start must build
valid inputs and run at both annual and monthly without error, producing aligned year figures.
The invariance *assertions* are separate (test_granularity_invariance.py); this only confirms the
matrix is runnable -- including the mid-year-start partial first year (issue #17)."""
import unittest

from ucfp.forecast.tests.granularity_harness import ANNUAL, MONTHLY, run_at, yearly_figures
from ucfp.forecast.tests.granularity_profiles import PROFILES, STARTS, TIERS, matrix


class GranularityProfileMatrixTest( unittest.TestCase ):

    def test_matrix_covers_every_profile_tier_and_start( self ):
        combos = [ ( profile, tier, start ) for profile, tier, start, _params in matrix() ]
        self.assertEqual( len( combos ), len( PROFILES ) * len( TIERS ) * len( STARTS ) )
        self.assertEqual( len( set( combos ) ), len( combos ) )

    def test_every_combo_runs_at_annual_and_monthly( self ):
        for profile_name, tier_name, start_name, params in matrix():
            for label, granularity in ( ( 'annual', ANNUAL ), ( 'monthly', MONTHLY ) ):
                with self.subTest(
                        profile = profile_name, tier = tier_name, start = start_name, granularity = label ):
                    figures = yearly_figures( run_at( params, granularity ), params )
                    self.assertEqual(
                        [ row.year for row in figures ],
                        list( range( params.start_date.year, params.end_date.year + 1 ) ) )
                    continue
            continue
