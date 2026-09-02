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
from typing import Optional

from django import forms

from common.forms import MoneyField, PercentField, StyledFormMixin
from common.rate import Rate

from ucfp.session_facts import PersonFacts, SessionFacts

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
    expected_return  = PercentField( label = 'Expected asset return', min_value = Decimal( '0' ) )
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
        # A below-inflation return would invert the opportunity-cost framing (the "above inflation" copy),
        # so reject it rather than model a negative real return.
        inflation       = cleaned.get( 'inflation' )
        expected_return = cleaned.get( 'expected_return' )
        if ( inflation is not None ) and ( expected_return is not None ) and ( expected_return < inflation ):
            self.add_error( 'expected_return', 'The expected return can’t be below inflation.' )
        return cleaned

    def session_facts( self ) -> SessionFacts:
        """The household facts as a neutral `SessionFacts` -- one person for a single household, two for a
        couple. These are the facts that can seed a Profile; the run assumptions are kept apart (see
        `assumptions_inputs`), so this bag stays feature-neutral."""
        people = [ self._person_facts( 0 ) ]
        if self.cleaned_data[ 'household' ] == HOUSEHOLD_COUPLE:
            people.append( self._person_facts( 1 ) )
        return SessionFacts( people = people )

    def _person_facts( self, index : int ) -> PersonFacts:
        data = self.cleaned_data
        return PersonFacts(
            birth_year                 = data[ f's{index}_birth_year' ],
            government_pension_monthly = data[ f's{index}_pia' ],
            life_expectancy            = data[ f's{index}_life' ] )

    def assumptions_inputs( self ) -> dict:
        """The validated run assumptions as a JSON-serializable dict (percents stringified) -- the
        SS-specific session slot, re-read as this form's next prefill and the results' economic inputs."""
        data = self.cleaned_data
        return {
            'inflation'        : str( data[ 'inflation' ] ),
            'expected_return'  : str( data[ 'expected_return' ] ),
            'benefits_payable' : str( data[ 'benefits_payable' ] ),
            'reduction_year'   : data[ 'reduction_year' ] }

    def flag_invalid_fields( self ) -> None:
        """Mark each erroring field's widget invalid for re-render: Bootstrap `is-invalid` (so the error
        summary's "highlighted fields" actually highlight) plus the ARIA a screen reader needs --
        `aria-invalid` and `aria-describedby` pointing at the field's error list (`_field_errors.html`
        renders that list under `{id}-errors`). Call before rendering a failed submit."""
        for name in self.errors:
            if name not in self.fields:
                continue                                    # a non-field ('__all__') error has no widget
            attrs = self.fields[ name ].widget.attrs
            attrs[ 'class' ]            = ( attrs.get( 'class', '' ) + ' is-invalid' ).strip()
            attrs[ 'aria-invalid' ]     = 'true'
            attrs[ 'aria-describedby' ] = f'{ self[ name ].auto_id }-errors'


# The per-person facts a claimant needs, and the run-assumption keys -- the completeness contract the
# results views gate on (see `is_runnable`). They mirror what `_claimant` and `claimants_and_assumptions`
# read below, so an incomplete household never reaches the unguarded int()/Decimal() conversions.
_CLAIMANT_FACTS  = ( 'birth_year', 'government_pension_monthly', 'life_expectancy' )
_ASSUMPTION_KEYS = ( 'inflation', 'benefits_payable', 'reduction_year' )


def is_runnable( facts : SessionFacts, assumptions_inputs : dict ) -> bool:
    """Whether the stored session facts and assumptions form a household the sweep can actually run: one or
    two people, each carrying every claiming fact, and all three run assumptions present. `SessionFacts` is
    a neutral, cross-tool bag, so another tool could leave a partial or oversized household here; the public
    results and drill-in views gate on this to send such a visit back to the form rather than erroring
    mid-compute."""
    if len( facts.people ) not in ( 1, 2 ):
        return False
    if not all( _person_is_complete( person ) for person in facts.people ):
        return False
    return all( assumptions_inputs.get( key ) not in ( None, '' ) for key in _ASSUMPTION_KEYS )


def _person_is_complete( person : PersonFacts ) -> bool:
    return all( getattr( person, fact ) is not None for fact in _CLAIMANT_FACTS )


def claimants_and_assumptions( facts : SessionFacts,
                               assumptions_inputs : dict ) -> tuple[ list[ Claimant ], Assumptions ]:
    """The compute core's typed inputs from the stored session slots: a `Claimant` per person in `facts`
    (higher earner derived later, in the compute core) and the `Assumptions` from the stored rates and the
    funding reduction. Assumes a runnable household (see `is_runnable`), which the views verify first."""
    claimants   = [ _claimant( person, index ) for index, person in enumerate( facts.people ) ]
    assumptions = Assumptions.from_inflation(
        inflation        = _rate_from_percent( assumptions_inputs[ 'inflation' ] ),
        benefits_payable = _rate_from_percent( assumptions_inputs[ 'benefits_payable' ] ),
        reduction_year   = int( assumptions_inputs[ 'reduction_year' ] ),
        expected_return  = _optional_rate_from_percent( assumptions_inputs.get( 'expected_return' ) ) )
    return claimants, assumptions


def default_inputs( assumptions : Assumptions ) -> dict:
    """The blank form's prefill: a couple household with empty people and the assumption fields seeded from
    `assumptions` (the anonymous system defaults, or a signed-in scenario's -- resolved by the caller). The
    expected return defaults to a conservative safe real rate above inflation (see
    `_default_expected_return_percent`); the people are left for the visitor to fill."""
    return {
        'household'        : HOUSEHOLD_COUPLE,
        'inflation'        : _percent_from_rate( assumptions.inflation ),
        'expected_return'  : _default_expected_return_percent( assumptions.inflation ),
        'benefits_payable' : _percent_from_rate( assumptions.benefits_payable ),
        'reduction_year'   : assumptions.reduction_year }


def _claimant( person : PersonFacts, index : int ) -> Claimant:
    return Claimant(
        name              = _PERSON_NAMES[ index ],
        birth_year        = int( person.birth_year ),
        pia_monthly       = Decimal( str( person.government_pension_monthly ) ),
        expected_lifetime = int( person.life_expectancy ) )


# The default expected return, as a real rate above inflation: a conservative, TIPS-anchored safe real
# return. Deferring Social Security is itself a guaranteed real return, so the honest opportunity-cost
# hurdle is a guaranteed alternative (~2% real), not a risky equity return. Expressed above whatever
# inflation is in effect, so the real default holds regardless of the inflation assumption.
_DEFAULT_REAL_RETURN = Rate( Decimal( '0.02' ) )


def _default_expected_return_percent( inflation : Rate ) -> str:
    """The default expected _nominal_ return: the conservative safe real rate above `inflation`."""
    return _percent_from_rate( Rate( inflation.fraction + _DEFAULT_REAL_RETURN.fraction ) )


def _rate_from_percent( percent ) -> Rate:
    """A `Rate` from a percent value (a whole-number-ish figure): 2.5 -> Rate(0.025)."""
    return Rate( Decimal( str( percent ) ) / Decimal( '100' ) )


def _optional_rate_from_percent( percent ) -> Optional[ Rate ]:
    """A `Rate` from a percent value, or None when absent/blank -- so a session stored before the expected
    return existed simply discounts at inflation (the pre-feature behavior) rather than failing."""
    if percent in ( None, '' ):
        return None
    return _rate_from_percent( percent )


def _percent_from_rate( rate : Rate ) -> str:
    """A percent string for a form initial from a `Rate`: Rate(0.025) -> '2.5', Rate(1) -> '100'
    (trailing zeros trimmed; fixed-point so a whole percent is not scientific notation)."""
    return format( ( rate.fraction * Decimal( '100' ) ).normalize(), 'f' )
