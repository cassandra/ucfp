"""Unit tests for the RMD helper itself: the cohort start age and the Uniform Lifetime factor.

The Forecast-level forcing is covered in `forecast/tests/test_rmd.py`; here we pin the pure
computation. The 1950-and-earlier cohort begins at 72, so the table must carry a 72 factor --
its omission would raise a KeyError the first year that cohort is due (regression guard).
"""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.us.rmd import required_minimum_distribution, rmd_start_age


class RmdHelperTests( unittest.TestCase ):

    def test_start_age_by_secure_2_cohort( self ):
        self.assertEqual( rmd_start_age( 1950 ), 72 )
        self.assertEqual( rmd_start_age( 1955 ), 73 )
        self.assertEqual( rmd_start_age( 1965 ), 75 )

    def test_no_distribution_before_the_cohort_start_age( self ):
        self.assertEqual( required_minimum_distribution( Decimal( '1000000' ), 74, 1965 ), Decimal( '0' ) )

    def test_age_72_uses_the_uniform_lifetime_factor_for_the_1950_cohort( self ):
        # The 1950-cohort's first RMD is at 72; the factor is 27.4, so a 274,000 balance yields a
        # clean 10,000. Guards against a missing 72 row (a KeyError for the earliest cohort).
        self.assertEqual(
            required_minimum_distribution( Decimal( '274000' ), 72, 1950 ), Decimal( '10000' ) )

    def test_ages_past_the_table_use_the_120_plus_factor( self ):
        # 130 is off the table; it falls back to the 120+ factor of 2.0 (half the balance).
        self.assertEqual(
            required_minimum_distribution( Decimal( '10000' ), 130, 1965 ), Decimal( '5000' ) )


if __name__ == '__main__':
    unittest.main()
