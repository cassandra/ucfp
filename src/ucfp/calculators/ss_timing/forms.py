"""The (login-free) Social Security claiming calculator's input form and the mapping between its raw
values and the compute core's typed inputs.

The form collects a household of one or two people (birth year, PIA, expected lifetime) and the economic
assumptions the sweep runs under (the SS cost-of-living adjustment, general inflation, and a funding
reduction). It is deliberately thin: validation lives here, but the raw values persist to the session and
drive the results page, so the value<->domain mapping (`claimants_and_assumptions`, `default_inputs`) is
standalone -- the results view rebuilds the domain inputs from the stored dict without a bound form.
"""
from datetime import date
from decimal import Decimal

from django import forms

from common.forms import MoneyField, PercentField, StyledFormMixin
from common.rate import Rate

from .compute import EARLIEST_CLAIM_AGE, Assumptions, Claimant

HOUSEHOLD_SINGLE = 'single'
HOUSEHOLD_COUPLE = 'couple'
_HOUSEHOLD_CHOICES = [ ( HOUSEHOLD_SINGLE, 'One person' ),
                       ( HOUSEHOLD_COUPLE, 'A couple' ) ]
# The two people's display identities, index-aligned (the primary, then the partner). The higher earner is
# derived by PIA in the compute core, so a person keeps its identity whichever way the earners sort.
_PERSON_NAMES  = ( 'Individual', 'Partner' )
_OLDEST_AGE    = 120


def _year_widget() -> forms.TextInput:
    """A text input wired for the year-only date picker (bootstrap-datepicker, initialised in
    ss_timing.js) -- the value stays a bare year, so prefill and parsing are unchanged."""
    return forms.TextInput( attrs = {
        'class': 'js-year-picker', 'autocomplete': 'off', 'inputmode': 'numeric',
        'placeholder': 'e.g. 1962' } )


class BenefitEstimateForm( StyledFormMixin, forms.Form ):
    """The benefit estimator's two fields: an average annual income and the monthly benefit at full
    retirement age it implies. The income drives the estimate (the jurisdiction facade computes it); the
    benefit stays editable so someone who already knows their figure can type it. Rendering and parsing
    only -- both are optional so a mid-interaction recompute never errors on a blank."""

    income  = MoneyField( required = False, min_value = Decimal( '0' ) )
    benefit = MoneyField( required = False, min_value = Decimal( '0' ) )


class InputsForm( StyledFormMixin, forms.Form ):
    """One or two people's claiming facts plus the economic assumptions. The partner fields are optional
    at the field level and required in `clean` only when the household is a couple, so switching to one
    person leaves them blank without a validation wall."""

    household        = forms.ChoiceField( choices = _HOUSEHOLD_CHOICES, initial = HOUSEHOLD_COUPLE,
                                          widget = forms.RadioSelect )
    s0_birth_year    = forms.IntegerField( label = 'Birth year', min_value = 1900, widget = _year_widget() )
    s0_pia           = MoneyField( label = 'Benefit at full retirement age (PIA)',
                                   min_value = Decimal( '0' ) )
    s0_life          = forms.IntegerField( label = 'Expected lifetime',
                                           min_value = EARLIEST_CLAIM_AGE, max_value = _OLDEST_AGE )
    s1_birth_year    = forms.IntegerField( label = 'Birth year', min_value = 1900, required = False,
                                           widget = _year_widget() )
    s1_pia           = MoneyField( label = 'Benefit at full retirement age (PIA)',
                                   min_value = Decimal( '0' ), required = False )
    s1_life          = forms.IntegerField( label = 'Expected lifetime', min_value = EARLIEST_CLAIM_AGE,
                                           max_value = _OLDEST_AGE, required = False )
    inflation        = PercentField( label = 'Inflation', min_value = Decimal( '0' ) )
    benefits_payable = PercentField( label = 'Reduce benefits to', min_value = Decimal( '0' ),
                                     max_value = Decimal( '100' ) )
    reduction_year   = forms.IntegerField( label = 'starting in', min_value = 2025, max_value = 2100 )

    def clean( self ) -> dict:
        """Enforce the couple's partner fields and reject a future birth year -- rules that span fields or
        need today's date, so they live here rather than on a single field."""
        cleaned = super().clean()
        if cleaned.get( 'household' ) == HOUSEHOLD_COUPLE:
            for part in ( 'birth_year', 'pia', 'life' ):
                if cleaned.get( f's1_{part}' ) in ( None, '' ):
                    self.add_error( f's1_{part}', 'Enter this for the partner.' )
        this_year = date.today().year
        for field_name in ( 's0_birth_year', 's1_birth_year' ):
            birth_year = cleaned.get( field_name )
            if birth_year is not None and birth_year > this_year:
                self.add_error( field_name, 'A birth year cannot be in the future.' )
        return cleaned

    def cleaned_inputs( self ) -> dict:
        """The validated values as a JSON-serializable dict (Decimals stringified) -- the shape persisted
        to the session and re-read as both the results' domain inputs and this form's next prefill. The
        partner keys are present only for a couple, so the household kind is recoverable from the dict."""
        data   = self.cleaned_data
        inputs = {
            'household'        : data[ 'household' ],
            's0_birth_year'    : data[ 's0_birth_year' ],
            's0_pia'           : str( data[ 's0_pia' ] ),
            's0_life'          : data[ 's0_life' ],
            'inflation'        : str( data[ 'inflation' ] ),
            'benefits_payable' : str( data[ 'benefits_payable' ] ),
            'reduction_year'   : data[ 'reduction_year' ] }
        if data[ 'household' ] == HOUSEHOLD_COUPLE:
            inputs.update( {
                's1_birth_year' : data[ 's1_birth_year' ],
                's1_pia'        : str( data[ 's1_pia' ] ),
                's1_life'       : data[ 's1_life' ] } )
        return inputs


def claimants_and_assumptions( inputs : dict ) -> tuple[ list[ Claimant ], Assumptions ]:
    """The compute core's typed inputs from a stored form dict: one `Claimant` (two for a couple, keyed by
    the partner fields being present) and the `Assumptions` from the rates and the funding reduction."""
    claimants = [ _claimant( inputs, 0 ) ]
    if inputs.get( 'household' ) == HOUSEHOLD_COUPLE:
        claimants.append( _claimant( inputs, 1 ) )
    assumptions = Assumptions.from_inflation(
        inflation        = _rate_from_percent( inputs[ 'inflation' ] ),
        benefits_payable = _rate_from_percent( inputs[ 'benefits_payable' ] ),
        reduction_year   = int( inputs[ 'reduction_year' ] ) )
    return claimants, assumptions


def default_inputs( assumptions : Assumptions ) -> dict:
    """The blank form's prefill: a couple household with empty people and the assumption fields seeded from
    `assumptions` (the anonymous system defaults, or a signed-in scenario's -- resolved by the caller).
    Only the assumption fields carry a value; the people are left for the visitor to fill."""
    return {
        'household'        : HOUSEHOLD_COUPLE,
        'inflation'        : _percent_from_rate( assumptions.inflation ),
        'benefits_payable' : _percent_from_rate( assumptions.benefits_payable ),
        'reduction_year'   : assumptions.reduction_year }


def _claimant( inputs : dict, index : int ) -> Claimant:
    return Claimant(
        name              = _PERSON_NAMES[ index ],
        birth_year        = int( inputs[ f's{index}_birth_year' ] ),
        pia_monthly       = Decimal( str( inputs[ f's{index}_pia' ] ) ),
        expected_lifetime = int( inputs[ f's{index}_life' ] ) )


def _rate_from_percent( percent ) -> Rate:
    """A `Rate` from a percent value (a whole-number-ish figure): 2.5 -> Rate(0.025)."""
    return Rate( Decimal( str( percent ) ) / Decimal( '100' ) )


def _percent_from_rate( rate : Rate ) -> str:
    """A percent string for a form initial from a `Rate`: Rate(0.025) -> '2.5', Rate(1) -> '100'
    (trailing zeros trimmed; fixed-point so a whole percent is not scientific notation)."""
    return format( ( rate.fraction * Decimal( '100' ) ).normalize(), 'f' )
