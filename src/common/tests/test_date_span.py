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


if __name__ == '__main__':
    unittest.main()
