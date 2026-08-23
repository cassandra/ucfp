"""Forms for the Financial Forecast hub.

`FrameForm` holds the run frame's when-controls (start, duration, interval); `ForecastForm` adds the
saved-scenario chooser and is what the hub submits, driving either a direct run or an Explore entry. The
frame vocabulary and its resolution live in `frames.py`; these forms just render fields from it.
"""
from django import forms

from common.forms import StyledFormMixin

from .frames import INTERVAL_CHOICES, START_CHOICES, START_EFFECTIVE


class FrameForm( StyledFormMixin, forms.Form ):
    """The run frame's when-controls, shared by the hub forms: where the run starts relative to the
    profile's effective date, how many years it spans, and its granularity."""

    start_from     = forms.ChoiceField(
        label = 'Start from', choices = START_CHOICES, initial = START_EFFECTIVE,
        help_text = "Defaults to your profile's date; a year-aligned start is approximate." )
    # No static default: the hub injects an age-based one per profile (see `default_forecast_duration_years`).
    duration_years = forms.IntegerField( label = 'Duration (years)', min_value = 1 )
    interval       = forms.ChoiceField(
        label = 'Interval', choices = INTERVAL_CHOICES, initial = 'year' )


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
