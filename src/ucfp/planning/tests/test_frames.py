"""`resolve_frame`: the run form's when-choices resolved into a `ForecastFrame` (issue #75).

The start is the profile's effective date, or a year-aligned override; the end runs the chosen
duration and then rounds up to a full final calendar year. These are the non-trivial pieces (the
rounding, and the year-aligned overrides), so they earn a committed test."""
import unittest
from datetime import date

from common.recurrence import Duration, TimeUnit
from ucfp.planning.forms import resolve_frame

_YEARLY = Duration( 1, TimeUnit.YEAR )


class ResolveFrameTests( unittest.TestCase ):

    def test_effective_start_runs_from_the_profile_date( self ):
        frame = resolve_frame( date( 2026, 7, 1 ), 'effective', 20, _YEARLY )
        self.assertEqual( frame.start_date, date( 2026, 7, 1 ) )

    def test_this_year_start_is_january_first_of_the_effective_year( self ):
        frame = resolve_frame( date( 2026, 7, 1 ), 'this_year', 20, _YEARLY )
        self.assertEqual( frame.start_date, date( 2026, 1, 1 ) )

    def test_next_year_start_is_january_first_of_the_following_year( self ):
        frame = resolve_frame( date( 2026, 7, 1 ), 'next_year', 20, _YEARLY )
        self.assertEqual( frame.start_date, date( 2027, 1, 1 ) )

    def test_end_rounds_up_to_a_full_final_calendar_year( self ):
        # a mid-year start's naive anniversary end (2046-06-30) rounds up to that year's Dec 31
        mid = resolve_frame( date( 2026, 7, 1 ), 'effective', 20, _YEARLY )
        self.assertEqual( mid.end_date, date( 2046, 12, 31 ) )
        # a January-aligned start lands exactly on Dec 31 -- 20 full years, 2026 through 2045
        aligned = resolve_frame( date( 2026, 7, 1 ), 'this_year', 20, _YEARLY )
        self.assertEqual( aligned.end_date, date( 2045, 12, 31 ) )

    def test_january_effective_date_collapses_effective_and_this_year( self ):
        effective = resolve_frame( date( 2026, 1, 1 ), 'effective', 20, _YEARLY )
        this_year = resolve_frame( date( 2026, 1, 1 ), 'this_year', 20, _YEARLY )
        self.assertEqual( effective.start_date, this_year.start_date )
        self.assertEqual( effective.end_date, this_year.end_date )
        self.assertEqual( effective.start_date, date( 2026, 1, 1 ) )

    def test_granularity_passes_through( self ):
        monthly = Duration( 1, TimeUnit.MONTH )
        frame = resolve_frame( date( 2026, 1, 1 ), 'effective', 10, monthly )
        self.assertEqual( frame.granularity, monthly )


if __name__ == '__main__':
    unittest.main()
