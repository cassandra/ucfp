"""Forms for the scenario-build page.

Plain forms whose composite `ScenarioBuildForm` materializes a typed `Scenario` (the
form->aggregate mapping lives here in the form layer, like the profile's). What this page adds
over the profile is library-backed selects: the economic outlook and lifestyle cost table are
chosen from the seeded parameter-set library, by `EconomicOutlookVariant` / `LifestyleScope`.
Tracer scope -- external factors, a lifestyle timeline, and one subject's retirement timing;
contributions, drawdown, planned moves, and life events come later. Tax defaults to current US
federal law (not yet solicited).
"""
from django import forms
from django.forms import formset_factory

from ucfp.parameter_sets.enums import EconomicOutlookVariant, LifestyleLevel, LifestyleScope
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile

from .schemas import LifestylePlan, LifestyleSegment, RetirementTiming, Scenario

# The single subject the tracer plans for, matching the profile's default subject handle.
_SUBJECT_HANDLE = 'subject'


class ExternalFactorsForm( forms.Form ):
    """Which curated economic outlook and lifestyle cost table the scenario draws from."""

    economic_outlook = forms.ChoiceField(
        label = 'Economic outlook', choices = EconomicOutlookVariant.choices() )
    lifestyle_scope  = forms.ChoiceField(
        label = 'Lifestyle cost table', choices = LifestyleScope.choices() )


class RetirementTimingForm( forms.Form ):
    """When the subject retires and claims the government pension."""

    retirement_date = forms.DateField( label = 'Retirement date', required = False )
    government_pension_claiming_age = forms.IntegerField(
        label = 'Pension claiming age', required = False, min_value = 0 )

    def is_set( self ) -> bool:
        return ( self.cleaned_data.get( 'retirement_date' ) is not None
                 or self.cleaned_data.get( 'government_pension_claiming_age' ) is not None )


class LifestyleSegmentForm( forms.Form ):
    """One span of the lifestyle timeline. A row with no start date is skipped."""

    start = forms.DateField( label = 'Starting', required = False )
    level = forms.ChoiceField( label = 'Lifestyle', choices = LifestyleLevel.choices(), required = False )

    def is_filled( self ) -> bool:
        return bool( self.cleaned_data.get( 'start' ) )

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'start' ) and not cleaned.get( 'level' ):
            raise forms.ValidationError(
                'Choose a lifestyle for this span, or clear its start date to drop the row.' )
        return cleaned


LifestyleSegmentFormSet = formset_factory( LifestyleSegmentForm, extra = 3 )


class ScenarioBuildForm:
    """The scenario page's form group -- external factors, retirement timing, and the lifestyle
    timeline -- and the assembly into a typed `Scenario`. Render via `factors`, `timing`, and
    `segments`."""

    _SEGMENT_PREFIX = 'segment'

    def __init__( self, data = None, scenario : Scenario = None ):
        factors_initial = self._factors_initial( scenario ) if scenario is not None else None
        timing_initial  = self._timing_initial( scenario ) if scenario is not None else None
        segment_initial = self._segment_initial( scenario ) if scenario is not None else None
        self.factors  = ExternalFactorsForm( data, initial = factors_initial )
        self.timing   = RetirementTimingForm( data, initial = timing_initial )
        self.segments = LifestyleSegmentFormSet(
            data, prefix = self._SEGMENT_PREFIX, initial = segment_initial )

    def is_valid( self ) -> bool:
        factors_valid  = self.factors.is_valid()
        timing_valid   = self.timing.is_valid()
        segments_valid = self.segments.is_valid()
        return factors_valid and timing_valid and segments_valid

    def to_scenario( self ) -> Scenario:
        factors = self.factors.cleaned_data
        segments = self._segments()
        # A cost table only applies over a timeline; with no segments there is no lifestyle.
        lifestyle = LifestylePlan(
            scope = LifestyleScope.from_name( factors[ 'lifestyle_scope' ] ),
            segments = segments ) if segments else None
        return Scenario(
            economic_outlook = EconomicOutlookVariant.from_name( factors[ 'economic_outlook' ] ),
            tax_forecast     = TaxForecastProfile(
                tax_law_type = TaxLawType.US_FEDERAL,
                tax_forecast_type = TaxForecastType.CURRENT_LAW ),
            lifestyle        = lifestyle,
            timing           = self._timing() )

    def _segments( self ) -> list:
        segments = list()
        for form in self.segments:
            if not form.is_filled():
                continue
            segments.append( LifestyleSegment(
                start = form.cleaned_data[ 'start' ],
                level = LifestyleLevel.from_name( form.cleaned_data[ 'level' ] ) ) )
        return segments

    def _timing( self ) -> list:
        if not self.timing.is_set():
            return list()
        timing = self.timing.cleaned_data
        return [ RetirementTiming(
            subject_handle = _SUBJECT_HANDLE,
            retirement_date = timing.get( 'retirement_date' ),
            government_pension_claiming_age = timing.get( 'government_pension_claiming_age' ) ) ]

    @staticmethod
    def _factors_initial( scenario : Scenario ) -> dict:
        scope = scenario.lifestyle.scope if scenario.lifestyle is not None else LifestyleScope.GENERAL
        return {
            'economic_outlook': scenario.economic_outlook.name.lower(),
            'lifestyle_scope' : scope.name.lower(),
        }

    @staticmethod
    def _timing_initial( scenario : Scenario ) -> dict:
        if not scenario.timing:
            return dict()
        timing = scenario.timing[ 0 ]
        return {
            'retirement_date': timing.retirement_date,
            'government_pension_claiming_age': timing.government_pension_claiming_age,
        }

    @staticmethod
    def _segment_initial( scenario : Scenario ) -> list:
        if scenario.lifestyle is None:
            return list()
        return [ { 'start': segment.start, 'level': segment.level.name.lower() }
                 for segment in scenario.lifestyle.segments ]
