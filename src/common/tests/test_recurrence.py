"""Tests for Recurrence occurrence-counting (exact, anchored, no amortization)."""
import unittest
from datetime import date

from common.recurrence import Duration, Recurrence, TimeUnit

START_2026 = date( 2026, 1, 1 )
END_2026 = date( 2026, 12, 31 )


def _every( count, unit, offset = None ):
    if offset is None:
        return Recurrence( Duration( count, unit ) )
    return Recurrence( Duration( count, unit ), offset )


def _in_year( recurrence, year ):
    """Occurrences of `recurrence` (referenced from Jan 1 2026) within `year`."""
    return recurrence.count_in( start = date( year, 1, 1 ), end = date( year, 12, 31 ), since = START_2026 )


class RecurrenceTests( unittest.TestCase ):

    def test_interval_must_be_positive( self ):
        with self.assertRaises( ValueError ):
            Recurrence( Duration( 0, TimeUnit.MONTH ) )

    def test_monthly_is_twelve_a_year( self ):
        monthly = _every( 1, TimeUnit.MONTH )
        self.assertEqual( monthly.count_in( start = START_2026, end = END_2026, since = START_2026 ), 12 )

    def test_quarterly_is_four_a_year( self ):
        quarterly = _every( 3, TimeUnit.MONTH )
        self.assertEqual( quarterly.count_in( start = START_2026, end = END_2026, since = START_2026 ), 4 )

    def test_sparse_purchase_lands_only_in_its_year( self ):
        # every 10 years, first occurrence at the reference date (2026)
        decadal = _every( 10, TimeUnit.YEAR )
        self.assertEqual( _in_year( decadal, 2026 ), 1 )
        self.assertEqual( _in_year( decadal, 2030 ), 0 )   # not in the intervening years
        self.assertEqual( _in_year( decadal, 2036 ), 1 )   # again a decade on

    def test_offset_delays_the_first_occurrence( self ):
        # every 10 years, but the first is 7 years out (e.g. a 3-year-old car)
        decadal = _every( 10, TimeUnit.YEAR, Duration( 7, TimeUnit.YEAR ) )
        self.assertEqual( _in_year( decadal, 2026 ), 0 )
        self.assertEqual( _in_year( decadal, 2033 ), 1 )

    def test_weekly_follows_the_calendar( self ):
        weekly = _every( 1, TimeUnit.WEEK )
        # 2026 has 53 Thursdays-from-Jan-1 anchored weeks (Jan 1 2026 + k*7 within the year)
        count = weekly.count_in( start = START_2026, end = END_2026, since = START_2026 )
        self.assertIn( count, ( 52, 53 ) )


if __name__ == '__main__':
    unittest.main()
