"""Unit tests for calendar-aligned period-span generation (issue #17).

`period_spans` slices the horizon into granularity intervals, each calendar year sliced from its
own start so no interval crosses December 31. A mid-year start yields a partial first year; an
end date that is not December 31 yields a partial last year; a January-1 whole-year run
reproduces plain calendar years (the regression guard). These are mechanical date edge cases, so
they earn a focused unit test."""
import unittest
from datetime import date, timedelta

from common.recurrence import Duration, TimeUnit
from ucfp.forecast.parameters import ForecastParameters
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile

_TAX = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW )
_YEARLY    = Duration( 1, TimeUnit.YEAR )
_QUARTERLY = Duration( 3, TimeUnit.MONTH )
_MONTHLY   = Duration( 1, TimeUnit.MONTH )


def _spans( start, end, granularity ):
    parameters = ForecastParameters(
        start_date = start, end_date = end, filing_status = FilingStatus.SINGLE,
        tax_forecast = _TAX, granularity = granularity )
    return [ ( span.start_date, span.end_date ) for span in parameters.period_spans() ]


class PeriodSpansTests( unittest.TestCase ):

    def test_january_yearly_is_plain_calendar_years( self ):
        self.assertEqual(
            _spans( date( 2026, 1, 1 ), date( 2028, 12, 31 ), _YEARLY ),
            [ ( date( 2026, 1, 1 ), date( 2026, 12, 31 ) ),
              ( date( 2027, 1, 1 ), date( 2027, 12, 31 ) ),
              ( date( 2028, 1, 1 ), date( 2028, 12, 31 ) ) ] )

    def test_midyear_yearly_has_a_partial_first_year( self ):
        self.assertEqual(
            _spans( date( 2026, 4, 1 ), date( 2028, 12, 31 ), _YEARLY ),
            [ ( date( 2026, 4, 1 ), date( 2026, 12, 31 ) ),       # partial first year
              ( date( 2027, 1, 1 ), date( 2027, 12, 31 ) ),
              ( date( 2028, 1, 1 ), date( 2028, 12, 31 ) ) ] )

    def test_midyear_monthly_aligns_to_calendar_months( self ):
        spans = _spans( date( 2026, 4, 1 ), date( 2026, 12, 31 ), _MONTHLY )
        self.assertEqual( len( spans ), 9 )                       # April through December
        self.assertEqual( spans[ 0 ], ( date( 2026, 4, 1 ), date( 2026, 4, 30 ) ) )
        self.assertEqual( spans[ -1 ], ( date( 2026, 12, 1 ), date( 2026, 12, 31 ) ) )

    def test_midyear_quarterly_clips_first_year_then_calendar_quarters( self ):
        self.assertEqual(
            _spans( date( 2026, 4, 1 ), date( 2027, 12, 31 ), _QUARTERLY ),
            [ ( date( 2026, 4, 1 ), date( 2026, 6, 30 ) ),
              ( date( 2026, 7, 1 ), date( 2026, 9, 30 ) ),
              ( date( 2026, 10, 1 ), date( 2026, 12, 31 ) ),
              ( date( 2027, 1, 1 ), date( 2027, 3, 31 ) ),        # full year realigns to Jan 1
              ( date( 2027, 4, 1 ), date( 2027, 6, 30 ) ),
              ( date( 2027, 7, 1 ), date( 2027, 9, 30 ) ),
              ( date( 2027, 10, 1 ), date( 2027, 12, 31 ) ) ] )

    def test_quarterly_start_off_the_quarter_clips_within_the_year( self ):
        # a May start: the partial first year's last quarter clips to Dec 31 (a 2-month interval)
        spans = _spans( date( 2026, 5, 1 ), date( 2026, 12, 31 ), _QUARTERLY )
        self.assertEqual(
            spans,
            [ ( date( 2026, 5, 1 ), date( 2026, 7, 31 ) ),
              ( date( 2026, 8, 1 ), date( 2026, 10, 31 ) ),
              ( date( 2026, 11, 1 ), date( 2026, 12, 31 ) ) ] )

    def test_trailing_partial_year_when_end_is_not_december_31( self ):
        spans = _spans( date( 2026, 1, 1 ), date( 2027, 3, 31 ), _MONTHLY )
        self.assertEqual( spans[ -1 ], ( date( 2027, 3, 1 ), date( 2027, 3, 31 ) ) )

    def test_no_interval_crosses_a_year_boundary( self ):
        for start, end, granularity in (
                ( date( 2026, 5, 1 ), date( 2029, 8, 31 ), _QUARTERLY ),
                ( date( 2026, 4, 1 ), date( 2030, 9, 30 ), _MONTHLY ),
                ( date( 2026, 6, 1 ), date( 2031, 12, 31 ), _YEARLY ) ):
            for span_start, span_end in _spans( start, end, granularity ):
                self.assertEqual( span_start.year, span_end.year )
            continue

    def test_intervals_tile_the_horizon_without_gap_or_overlap( self ):
        start, end = date( 2026, 4, 1 ), date( 2030, 9, 30 )
        spans = _spans( start, end, _MONTHLY )
        self.assertEqual( spans[ 0 ][ 0 ], start )
        self.assertEqual( spans[ -1 ][ 1 ], end )
        for ( _prev_start, prev_end ), ( next_start, _next_end ) in zip( spans, spans[ 1: ] ):
            self.assertEqual( next_start, prev_end + timedelta( days = 1 ) )
            continue

    def test_first_of_month_required( self ):
        with self.assertRaises( ValueError ):
            ForecastParameters(
                start_date = date( 2026, 4, 15 ), end_date = date( 2027, 12, 31 ),
                filing_status = FilingStatus.SINGLE, tax_forecast = _TAX )


if __name__ == '__main__':
    unittest.main()
