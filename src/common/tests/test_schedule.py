"""Tests for the Schedule windowed-segment resolver."""
import unittest
from dataclasses import dataclass
from datetime import date

from common.date_window import DateWindow
from common.schedule import Schedule


@dataclass( frozen = True )
class _Segment:
    window : DateWindow
    label  : str


class ScheduleTests( unittest.TestCase ):

    def test_empty_resolves_to_none( self ):
        self.assertIsNone( Schedule().at( date( 2026, 1, 1 ) ) )

    def test_constant_is_in_effect_throughout( self ):
        schedule = Schedule.constant( _Segment( DateWindow(), 'flat' ) )
        self.assertEqual( schedule.at( date( 1990, 1, 1 ) ).label, 'flat' )
        self.assertEqual( schedule.at( date( 2099, 1, 1 ) ).label, 'flat' )

    def test_first_covering_segment_wins( self ):
        schedule = Schedule( (
            _Segment( DateWindow( end = date( 2030, 12, 31 ) ), 'early' ),
            _Segment( DateWindow( start = date( 2031, 1, 1 ) ), 'late' ),
        ) )
        self.assertEqual( schedule.at( date( 2028, 6, 1 ) ).label, 'early' )
        self.assertEqual( schedule.at( date( 2035, 6, 1 ) ).label, 'late' )

    def test_gap_resolves_to_none( self ):
        schedule = Schedule( (
            _Segment( DateWindow( start = date( 2031, 1, 1 ), end = date( 2040, 12, 31 ) ), 'mid' ),
        ) )
        self.assertIsNone( schedule.at( date( 2026, 1, 1 ) ) )


if __name__ == '__main__':
    unittest.main()
