"""Forecast frame policy: the run's when-vocabulary (start, duration, interval), how those choices resolve
into a `ForecastFrame`, and the default horizon.

Kept separate from `forms.py` so non-form callers -- the hub view and the example-org seed -- get frame
logic without importing a Django-forms module. `forms.py` builds its fields from the vocabulary here.
"""
from datetime import date, timedelta

from common.datetime_utils import age_on
from common.recurrence import Duration, TimeUnit

from .materialization import ForecastFrame

INTERVAL_CHOICES = [
    ( 'year', 'Yearly' ),
    ( 'quarter', 'Quarterly' ),
    ( 'month', 'Monthly' ),
]

# The run frame's granularity per interval choice (each divides 12, as the engine requires).
GRANULARITY = {
    'year'    : Duration( 1, TimeUnit.YEAR ),
    'quarter' : Duration( 3, TimeUnit.MONTH ),
    'month'   : Duration( 1, TimeUnit.MONTH ),
}

# Where the forecast starts, relative to the chosen profile's effective date. The default runs
# from the effective date itself (exact -- the facts hold there); the year-aligned options start
# at January 1 of the effective date's year or the next, to avoid an untaxed partial first year.
START_EFFECTIVE = 'effective'
START_THIS_YEAR = 'this_year'
START_NEXT_YEAR = 'next_year'
START_CHOICES = [
    ( START_EFFECTIVE, "The profile's date" ),
    ( START_THIS_YEAR, 'Start of this year' ),
    ( START_NEXT_YEAR, 'Start of next year' ),
]


def resolve_frame(
        effective_date : date, start_choice : str, duration_years : int,
        granularity : Duration ) -> ForecastFrame:
    """Resolve the run form's when-choices into a `ForecastFrame`. The start is the profile's
    effective date by default, or January 1 of that year (`this_year`) or the next (`next_year`) --
    a year-aligned start avoids an untaxed partial first year. The end runs `duration_years` from
    the start, then rounds up to that year's December 31 so the span always closes on a full
    calendar year (no untaxed partial trailing year)."""
    if start_choice == START_THIS_YEAR:
        start = date( effective_date.year, 1, 1 )
    elif start_choice == START_NEXT_YEAR:
        start = date( effective_date.year + 1, 1, 1 )
    else:
        start = effective_date
    naive_end = start.replace( year = start.year + duration_years ) - timedelta( days = 1 )
    return ForecastFrame(
        start_date = start, end_date = date( naive_end.year, 12, 31 ), granularity = granularity )


# The default forecast horizon runs the youngest household member to this age; the small floor only guards
# the degenerate cases (no subjects, or a youngest already near/past the target) so the frame stays valid.
FORECAST_THROUGH_AGE = 90
FORECAST_MIN_YEARS   = 10


def default_forecast_duration_years( profile, start_date : date ) -> int:
    """The default run length: enough years for the *youngest* household member to reach
    `FORECAST_THROUGH_AGE` as of `start_date`, floored at `FORECAST_MIN_YEARS`. Drives the hub's first-time
    duration default and the example seed's horizon. The youngest anchors it because they are the likely
    last survivor, so the window covers the surviving spouse's later years -- the crux of "can I retire".
    (The oldest would cut those years off; modeled death events handle the older member's absence inside
    the window, so this stays a pure age formula.)"""
    ages = [ age_on( subject.birthdate, start_date ) for subject in profile.subjects ]
    if not ages:
        return FORECAST_MIN_YEARS
    return max( FORECAST_MIN_YEARS, FORECAST_THROUGH_AGE - min( ages ) )
