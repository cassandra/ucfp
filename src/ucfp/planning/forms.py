"""Forms for the Financial Forecast hub.

The run form makes the whole forecast bundle explicit -- which profile, which plans, which
assumptions, and the frame (duration + interval). The profile is shown "as of {month year}" and
defaults to the most recent; it is a real chooser as monthly versions accumulate. Profile, plans,
and assumptions choices are the organization's, injected by the view.
"""
from django import forms

from common.recurrence import Duration, TimeUnit

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


class RunForm( forms.Form ):
    """The forecast bundle: which profile, plans, and assumptions to run, and the frame. The choices
    are injected by the view from the organization's records; the profile defaults to the most
    recent."""

    profile        = forms.ChoiceField( label = 'Profile' )
    plans          = forms.ChoiceField( label = 'Plans' )
    assumptions    = forms.ChoiceField( label = 'Assumptions' )
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
