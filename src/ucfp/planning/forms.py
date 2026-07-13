"""Forms for the Financial Forecast hub.

The run form makes the whole forecast bundle explicit -- which profile, which plans, which
assumptions, and the frame (duration + interval). The profile is shown "as of {month year}" and
defaults to the most recent; it is a real chooser as monthly versions accumulate. Profile, plans,
and assumptions choices are the organization's, injected by the view.
"""
from datetime import date, timedelta

from django import forms

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


class RunForm( forms.Form ):
    """The forecast bundle: which profile, plans, and assumptions to run, and the frame. The choices
    are injected by the view from the organization's records; the profile defaults to the most
    recent."""

    profile        = forms.ChoiceField( label = 'Profile' )
    plans          = forms.ChoiceField( label = 'Plans' )
    assumptions    = forms.ChoiceField( label = 'Assumptions' )
    start_from     = forms.ChoiceField(
        label = 'Start from', choices = _START_CHOICES, initial = _START_EFFECTIVE,
        help_text = (
            "Runs from the profile's effective date by default. Starting from the beginning of this "
            "or next year instead projects the same facts from that date, so the run is approximate "
            "unless the profile's balances already match that start." ) )
    duration_years = forms.IntegerField( label = 'Duration (years)', min_value = 1, initial = 40 )
    interval       = forms.ChoiceField(
        label = 'Interval', choices = _INTERVAL_CHOICES, initial = 'year' )

    def __init__( self, *args, profiles = None, plans = None, assumptions = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self.fields[ 'profile' ].choices = [
            ( str( profile.uuid ), f'as of {profile.effective_date:%B %Y}' )
            for profile in ( profiles or [] ) ]
        self.fields[ 'plans' ].choices = [
            ( str( plan.uuid ), plan.label ) for plan in ( plans or [] ) ]
        self.fields[ 'assumptions' ].choices = [
            ( str( item.uuid ), item.label ) for item in ( assumptions or [] ) ]
