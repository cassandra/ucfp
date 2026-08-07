"""Tests for the DateSpan value object's derived properties."""
import unittest
from datetime import date

from common.date_span import DateSpan


class DateSpanMonthsTest( unittest.TestCase ):
    """`months` counts the whole calendar months an inclusive, month-aligned span covers."""

    def test_single_calendar_month_is_one( self ):
        self.assertEqual( DateSpan( date( 2026, 3, 1 ), date( 2026, 3, 31 ) ).months, 1 )

    def test_calendar_year_is_twelve( self ):
        self.assertEqual( DateSpan( date( 2026, 1, 1 ), date( 2026, 12, 31 ) ).months, 12 )

    def test_partial_year_from_mid_year_start( self ):
        # July through December -- a mid-year forecast start's partial first period.
        self.assertEqual( DateSpan( date( 2026, 7, 1 ), date( 2026, 12, 31 ) ).months, 6 )

    def test_spans_year_boundary( self ):
        # November 2026 through February 2027.
        self.assertEqual( DateSpan( date( 2026, 11, 1 ), date( 2027, 2, 28 ) ).months, 4 )


class DateSpanMonthIndexTest( unittest.TestCase ):
    """`month_index_of` places a date's month within the span, zero-based from the start month."""

    def test_month_index_is_zero_based_from_the_start_month( self ):
        span = DateSpan( date( 2026, 1, 1 ), date( 2026, 12, 31 ) )
        self.assertEqual( span.month_index_of( date( 2026, 1, 15 ) ), 0 )    # first month, day ignored
        self.assertEqual( span.month_index_of( date( 2026, 6, 1 ) ), 5 )     # June is index 5
        self.assertEqual( span.month_index_of( span.end_date ) + 1, span.months )

    def test_month_index_across_a_year_boundary( self ):
        span = DateSpan( date( 2026, 11, 1 ), date( 2027, 2, 28 ) )
        self.assertEqual( span.month_index_of( date( 2027, 1, 1 ) ), 2 )     # Nov=0, Dec=1, Jan=2


if __name__ == '__main__':
    unittest.main()
