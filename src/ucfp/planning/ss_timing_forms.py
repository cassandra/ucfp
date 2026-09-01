"""The (login-free) Social Security claiming calculator's input form and the mapping between its raw
values and the compute core's typed inputs.

The form collects a household of one or two people (birth year, PIA, expected lifetime) and the economic
assumptions the sweep runs under (COLA, present-value discount, retained benefits). It is deliberately
thin: validation lives here, but the raw values persist to the session and drive the results page, so the
value<->domain mapping (`claimants_and_assumptions`, `default_inputs`) is standalone -- the results view
rebuilds the domain inputs from the stored dict without a bound form.
"""
from datetime import date
from decimal import Decimal

from django import forms

from common.forms import MoneyField, PercentField, StyledFormMixin
from common.rate import Rate

from .ss_timing import EARLIEST_CLAIM_AGE, Assumptions, Claimant

HOUSEHOLD_SINGLE = 'single'
HOUSEHOLD_COUPLE = 'couple'
_HOUSEHOLD_CHOICES = [ ( HOUSEHOLD_SINGLE, 'Just me' ),
                       ( HOUSEHOLD_COUPLE, 'Me and my spouse / partner' ) ]
# The two people's names, index-aligned; the higher earner is derived by PIA in the compute core, so
# these are display identities only (the primary, then the partner).
_PERSON_NAMES  = ( 'You', 'Spouse or partner' )
_OLDEST_AGE    = 120


class SocialSecurityTimingForm( StyledFormMixin, forms.Form ):
    """One or two people's claiming facts plus the economic assumptions. The partner fields are optional
    at the field level and required in `clean` only when the household is a couple, so switching to
    "Just me" leaves them blank without a validation wall."""

    household        = forms.ChoiceField( choices = _HOUSEHOLD_CHOICES, initial = HOUSEHOLD_COUPLE,
                                          widget = forms.RadioSelect )
    s0_birth_year    = forms.IntegerField( label = 'Birth year', min_value = 1900 )
    s0_pia           = MoneyField( label = 'Benefit at full retirement age (PIA)',
                                   min_value = Decimal( '0' ) )
    s0_life          = forms.IntegerField( label = 'Plan through age',
                                           min_value = EARLIEST_CLAIM_AGE, max_value = _OLDEST_AGE )
    s1_birth_year    = forms.IntegerField( label = 'Birth year', min_value = 1900, required = False )
    s1_pia           = MoneyField( label = 'Benefit at full retirement age (PIA)',
                                   min_value = Decimal( '0' ), required = False )
    s1_life          = forms.IntegerField( label = 'Plan through age', min_value = EARLIEST_CLAIM_AGE,
                                           max_value = _OLDEST_AGE, required = False )
    cola             = PercentField( label = 'Annual COLA', min_value = Decimal( '0' ) )
    discount         = PercentField( label = 'Present-value discount', min_value = Decimal( '0' ) )
    benefits_payable = PercentField( label = 'Benefits payable', min_value = Decimal( '0' ),
                                     max_value = Decimal( '100' ) )

    def clean( self ) -> dict:
        """Enforce the couple's partner fields and reject a future birth year -- rules that span fields or
        need today's date, so they live here rather than on a single field."""
        cleaned = super().clean()
        if cleaned.get( 'household' ) == HOUSEHOLD_COUPLE:
            for part in ( 'birth_year', 'pia', 'life' ):
                if cleaned.get( f's1_{part}' ) in ( None, '' ):
                    self.add_error( f's1_{part}', 'Enter this for your spouse or partner.' )
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
            'cola'             : str( data[ 'cola' ] ),
            'discount'         : str( data[ 'discount' ] ),
            'benefits_payable' : str( data[ 'benefits_payable' ] ) }
        if data[ 'household' ] == HOUSEHOLD_COUPLE:
            inputs.update( {
                's1_birth_year' : data[ 's1_birth_year' ],
                's1_pia'        : str( data[ 's1_pia' ] ),
                's1_life'       : data[ 's1_life' ] } )
        return inputs


def claimants_and_assumptions( inputs : dict ) -> tuple[ list[ Claimant ], Assumptions ]:
    """The compute core's typed inputs from a stored form dict: one `Claimant` (two for a couple, keyed by
    the partner fields being present) and the `Assumptions` from the three percent rates. The discount
    percent is the general inflation the present value discounts at."""
    claimants = [ _claimant( inputs, 0 ) ]
    if inputs.get( 'household' ) == HOUSEHOLD_COUPLE:
        claimants.append( _claimant( inputs, 1 ) )
    assumptions = Assumptions(
        inflation        = _rate_from_percent( inputs[ 'discount' ] ),
        cola             = _rate_from_percent( inputs[ 'cola' ] ),
        benefits_payable = _rate_from_percent( inputs[ 'benefits_payable' ] ) )
    return claimants, assumptions


def default_inputs( assumptions : Assumptions ) -> dict:
    """The blank form's prefill: a couple household with empty people and the assumption percents seeded
    from `assumptions` (the anonymous system defaults, or a signed-in scenario's -- resolved by the
    caller). Only the assumption fields carry a value; the people are left for the visitor to fill."""
    return {
        'household'        : HOUSEHOLD_COUPLE,
        'cola'             : _percent_from_rate( assumptions.cola ),
        'discount'         : _percent_from_rate( assumptions.inflation ),
        'benefits_payable' : _percent_from_rate( assumptions.benefits_payable ) }


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
    """A percent string for a form initial from a `Rate`: Rate(0.025) -> '2.5' (trailing zeros trimmed)."""
    return str( ( rate.fraction * Decimal( '100' ) ).normalize() )
