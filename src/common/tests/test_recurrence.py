"""Tests for cadence occurrence-counting (exact, anchored, no amortization)."""
import unittest
from datetime import date, timedelta

from common.recurrence import Duration, OneTime, Recurrence, TimeUnit

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


_MONTH_SPANS_2030 = [
    ( date( 2030, month, 1 ),
      date( 2030, 12, 31 ) if month == 12 else date( 2030, month + 1, 1 ) - timedelta( days = 1 ) )
    for month in range( 1, 13 ) ]
_QUARTER_SPANS_2030 = [
    ( date( 2030, 1, 1 ), date( 2030, 3, 31 ) ), ( date( 2030, 4, 1 ), date( 2030, 6, 30 ) ),
    ( date( 2030, 7, 1 ), date( 2030, 9, 30 ) ), ( date( 2030, 10, 1 ), date( 2030, 12, 31 ) ) ]


class OneTimeTests( unittest.TestCase ):

    def test_fires_once_in_the_interval_containing_its_date( self ):
        once = OneTime( date( 2030, 6, 15 ) )
        self.assertEqual(
            once.count_in( start = date( 2030, 1, 1 ), end = date( 2030, 12, 31 ), since = START_2026 ), 1 )

    def test_does_not_fire_in_other_years( self ):
        once = OneTime( date( 2030, 6, 15 ) )
        self.assertEqual( _in_year_once( once, 2029 ), 0 )
        self.assertEqual( _in_year_once( once, 2031 ), 0 )

    def test_exactly_one_occurrence_per_year_regardless_of_granularity( self ):
        # The whole point: a one-time fires once total, in the one sub-period that contains it,
        # at every granularity -- so it inherits the occurrence invariance contract (issue #16).
        once = OneTime( date( 2030, 6, 15 ) )
        annual = once.count_in( start = date( 2030, 1, 1 ), end = date( 2030, 12, 31 ), since = START_2026 )
        quarterly = sum(
            once.count_in( start = s, end = e, since = START_2026 ) for s, e in _QUARTER_SPANS_2030 )
        monthly = sum(
            once.count_in( start = s, end = e, since = START_2026 ) for s, e in _MONTH_SPANS_2030 )
        self.assertEqual( ( annual, quarterly, monthly ), ( 1, 1, 1 ) )

    def test_lands_in_the_correct_sub_period( self ):
        once = OneTime( date( 2030, 6, 15 ) )
        june = ( date( 2030, 6, 1 ), date( 2030, 6, 30 ) )
        firing_months = [
            ( start.month ) for start, end in _MONTH_SPANS_2030
            if once.count_in( start = start, end = end, since = START_2026 ) == 1 ]
        self.assertEqual( firing_months, [ 6 ] )
        self.assertEqual( once.count_in( start = june[ 0 ], end = june[ 1 ], since = START_2026 ), 1 )

    def test_range_boundaries_are_inclusive( self ):
        once = OneTime( date( 2030, 6, 15 ) )
        self.assertEqual(
            once.count_in( start = date( 2030, 6, 15 ), end = date( 2030, 6, 30 ), since = START_2026 ), 1 )
        self.assertEqual(
            once.count_in( start = date( 2030, 6, 1 ), end = date( 2030, 6, 15 ), since = START_2026 ), 1 )

    def test_since_is_ignored( self ):
        once = OneTime( date( 2030, 6, 15 ) )
        span = dict( start = date( 2030, 1, 1 ), end = date( 2030, 12, 31 ) )
        self.assertEqual(
            once.count_in( since = date( 1900, 1, 1 ), **span ),
            once.count_in( since = date( 2050, 1, 1 ), **span ) )


def _in_year_once( cadence, year ):
    return cadence.count_in( start = date( year, 1, 1 ), end = date( year, 12, 31 ), since = START_2026 )


if __name__ == '__main__':
    unittest.main()
