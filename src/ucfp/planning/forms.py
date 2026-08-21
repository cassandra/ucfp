"""Forms for the Financial Forecast hub.

`FrameForm` holds the run frame's when-controls (start, duration, interval); `ForecastForm` adds the
saved-scenario chooser and is what the hub submits, driving either a direct run or an Explore entry.
`RunForm` -- the older profile + plans + assumptions bundle chooser -- also builds on `FrameForm`; its
choices are the organization's, injected by the view. Frame resolution is shared via `resolve_frame`.
"""
from datetime import date, timedelta

from django import forms

from common.datetime_utils import age_on
from common.forms import StyledFormMixin
from common.recurrence import Duration, TimeUnit

from .materialization import ForecastFrame

_INTERVAL_CHOICES = [
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
_START_EFFECTIVE = 'effective'
_START_THIS_YEAR = 'this_year'
_START_NEXT_YEAR = 'next_year'
_START_CHOICES = [
    ( _START_EFFECTIVE, "The profile's date" ),
    ( _START_THIS_YEAR, 'Start of this year' ),
    ( _START_NEXT_YEAR, 'Start of next year' ),
]


def resolve_frame(
        effective_date : date, start_choice : str, duration_years : int,
        granularity : Duration ) -> ForecastFrame:
    """Resolve the run form's when-choices into a `ForecastFrame`. The start is the profile's
    effective date by default, or January 1 of that year (`this_year`) or the next (`next_year`) --
    a year-aligned start avoids an untaxed partial first year. The end runs `duration_years` from
    the start, then rounds up to that year's December 31 so the span always closes on a full
    calendar year (no untaxed partial trailing year)."""
    if start_choice == _START_THIS_YEAR:
        start = date( effective_date.year, 1, 1 )
    elif start_choice == _START_NEXT_YEAR:
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
    duration default and the sample seed's horizon. The youngest anchors it because they are the likely
    last survivor, so the window covers the surviving spouse's later years -- the crux of "can I retire".
    (The oldest would cut those years off; modeled death events handle the older member's absence inside
    the window, so this stays a pure age formula.)"""
    ages = [ age_on( subject.birthdate, start_date ) for subject in profile.subjects ]
    if not ages:
        return FORECAST_MIN_YEARS
    return max( FORECAST_MIN_YEARS, FORECAST_THROUGH_AGE - min( ages ) )


class FrameForm( StyledFormMixin, forms.Form ):
    """The run frame's when-controls, shared by the hub forms: where the run starts relative to the
    profile's effective date, how many years it spans, and its granularity."""

    start_from     = forms.ChoiceField(
        label = 'Start from', choices = _START_CHOICES, initial = _START_EFFECTIVE,
        help_text = "Defaults to your profile's date; a year-aligned start is approximate." )
    # No static default: the hub injects an age-based one per profile (see `default_forecast_duration_years`).
    duration_years = forms.IntegerField( label = 'Duration (years)', min_value = 1 )
    interval       = forms.ChoiceField(
        label = 'Interval', choices = _INTERVAL_CHOICES, initial = 'year' )


class RunForm( FrameForm ):
    """The forecast bundle: which profile, plans, and assumptions to run, and the frame. The choices
    are injected by the view from the organization's records; the profile defaults to the most
    recent."""

    profile        = forms.ChoiceField( label = 'Profile' )
    plans          = forms.ChoiceField( label = 'Plans' )
    assumptions    = forms.ChoiceField( label = 'Assumptions' )
    field_order    = [ 'profile', 'plans', 'assumptions', 'start_from', 'duration_years', 'interval' ]

    def __init__( self, *args, profiles = None, plans = None, assumptions = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self.fields[ 'profile' ].choices = [
            ( str( profile.uuid ), f'as of {profile.effective_date:%B %Y}' )
            for profile in ( profiles or [] ) ]
        self.fields[ 'plans' ].choices = [
            ( str( plan.uuid ), plan.label ) for plan in ( plans or [] ) ]
        self.fields[ 'assumptions' ].choices = [
            ( str( item.uuid ), item.label ) for item in ( assumptions or [] ) ]


class ForecastForm( FrameForm ):
    """The hub's forecast bundle: which saved scenario to project, and the frame to project it over. The
    same submission drives either hub action -- run the scenario as-is, or open it in Explore. Scenario
    choices are injected by the view from the organization's saved scenarios."""

    scenario    = forms.ChoiceField( label = 'Scenario' )
    field_order = [ 'scenario', 'start_from', 'duration_years', 'interval' ]

    def __init__( self, *args, scenarios = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self.fields[ 'scenario' ].choices = [
            ( str( scenario.uuid ), scenario.label ) for scenario in ( scenarios or [] ) ]
