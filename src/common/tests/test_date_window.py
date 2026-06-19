"""Tests for the DateWindow value object (bounded/unbounded coverage)."""
import unittest
from datetime import date

from common.date_window import DateWindow


class DateWindowTests( unittest.TestCase ):

    def test_unbounded_covers_everything( self ):
        window = DateWindow()
        self.assertTrue( window.covers( date( 1900, 1, 1 ) ) )
        self.assertTrue( window.covers( date( 2100, 1, 1 ) ) )

    def test_start_only_is_open_ended( self ):
        window = DateWindow( start = date( 2030, 1, 1 ) )
        self.assertFalse( window.covers( date( 2029, 12, 31 ) ) )
        self.assertTrue( window.covers( date( 2030, 1, 1 ) ) )        # inclusive
        self.assertTrue( window.covers( date( 2099, 1, 1 ) ) )

    def test_end_only_is_open_started( self ):
        window = DateWindow( end = date( 2030, 12, 31 ) )
        self.assertTrue( window.covers( date( 1990, 1, 1 ) ) )
        self.assertTrue( window.covers( date( 2030, 12, 31 ) ) )      # inclusive
        self.assertFalse( window.covers( date( 2031, 1, 1 ) ) )

    def test_bounded_both_sides( self ):
        window = DateWindow( start = date( 2026, 1, 1 ), end = date( 2030, 12, 31 ) )
        self.assertFalse( window.covers( date( 2025, 12, 31 ) ) )
        self.assertTrue( window.covers( date( 2028, 6, 1 ) ) )
        self.assertFalse( window.covers( date( 2031, 1, 1 ) ) )


if __name__ == '__main__':
    unittest.main()
