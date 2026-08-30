"""Shared form widgets for the inputs area.

`IsoDateInput` is the day-resolution presentation for a date field. It renders and parses the canonical
ISO `YYYY-MM-DD` the server reads, and tags the input so `inputs.js` enhances it with a date picker
tuned to the field's planning `context`: birthdates sit decades in the past, planning dates decades
ahead, so the picker must not be anchored to the current month. Without JavaScript the field degrades
to a plain ISO text box, which the server still accepts -- the picker is a progressive enhancement.

`MonthDateInput` / `MonthField` are the month-resolution variant for planning dates that are only
meaningful to the month (a payoff month, a sale month): they solicit `YYYY-MM` and store a real `date`
normalized to mid-month. See their docstrings for the mid-month rationale.
"""
from decimal import Decimal

from django import forms

from common.rate import Rate

from ucfp.environment.constants import AppConst
from ucfp.jurisdiction.us.subdivision_tax import USState, exemption_words, representative_rate


def percent_str( rate : Rate ) -> str:
    """A `Rate` as a bare percent string, trailing zeros trimmed: 0.06 -> '6', 0.0307 -> '3.07'."""
    return format( ( rate.fraction * Decimal( '100' ) ).normalize(), 'f' )


class StateRateSelect( forms.Select ):
    """A state <select> that tags each option with its representative income-tax rate (percent) and its
    retirement-income exemption status words, so the client can auto-fill the rate and show the applied
    exemptions when the state changes. The blank 'other / not listed' option and no-income-tax states
    carry a zero rate and no exemption words (there is nothing to exempt)."""

    def create_option( self, name, value, label, selected, index, subindex = None, attrs = None ):
        option = super().create_option( name, value, label, selected, index, subindex, attrs )
        state  = USState.from_name( str( value ) ) if value else None
        rate   = representative_rate( state ) if state is not None else None
        percent = percent_str( rate ) if rate is not None else '0'
        # Exemption words only for a state that actually levies a tax; blank otherwise (nothing applies).
        levies_tax = bool( rate is not None and rate.fraction )
        ss_status, retirement_status = exemption_words( state ) if levies_tax else ( '', '' )
        option[ 'attrs' ][ f'data-{AppConst.STATE_RATE_DATA_ATTR}' ]              = percent
        option[ 'attrs' ][ f'data-{AppConst.STATE_SS_STATUS_DATA_ATTR}' ]         = ss_status
        option[ 'attrs' ][ f'data-{AppConst.STATE_RETIREMENT_STATUS_DATA_ATTR}' ] = retirement_status
        return option


class IsoDateInput( forms.DateInput ):
    """A date input rendered/parsed as canonical ISO and hooked for picker enhancement. `context` is
    one of `AppConst.DATE_CONTEXT_*` and rides along as a data-attribute the client reads to tune the
    picker; it defaults to the common forward-looking case. Subclasses override the three class
    attributes below to change resolution (see `MonthDateInput`)."""

    FORMAT      = '%Y-%m-%d'    # how a value is rendered and parsed
    PLACEHOLDER = 'YYYY-MM-DD'
    PRECISION   = None          # a `DATE_PRECISION_*` token, or None for full day precision

    def __init__( self, *, context = AppConst.DATE_CONTEXT_FUTURE, attrs = None ):
        # Render as a Bootstrap control by default (so a date is styled without depending on a form-level
        # mixin, which never runs over dynamically-added fields), merging -- not replacing -- any class
        # the caller adds.
        attrs   = dict( attrs or {} )
        classes = ( f'form-control {AppConst.DATE_FIELD_CLASS} ' + attrs.pop( 'class', '' ) ).strip()
        hooks   = {
            'class'                                   : classes,
            f'data-{AppConst.DATE_CONTEXT_DATA_ATTR}' : context,
            'autocomplete'                            : 'off',
            'placeholder'                             : self.PLACEHOLDER,
        }
        # Precision is orthogonal to context (a field may be both past-bounded and month-resolution), so
        # it rides its own data-attribute -- emitted only when the field is coarser than a full day.
        if self.PRECISION is not None:
            hooks[ f'data-{AppConst.DATE_PRECISION_DATA_ATTR}' ] = self.PRECISION
        hooks.update( attrs )
        super().__init__( attrs = hooks, format = self.FORMAT )


class MonthDateInput( IsoDateInput ):
    """`IsoDateInput` at month resolution: renders/parses `YYYY-MM` and tags itself so `inputs.js` opens
    the picker on a month grid. Only the presentation changes here; the stored day is normalized by
    `MonthField`."""

    FORMAT      = '%Y-%m'
    PLACEHOLDER = 'YYYY-MM'
    PRECISION   = AppConst.DATE_PRECISION_MONTH


class MonthField( forms.DateField ):
    """A month-resolution date: solicited and shown as `YYYY-MM`, stored as a real `date` normalized to
    the 15th of the month. Mid-month matches the engine's deliberate mid-period convention (interval
    accumulations are dated mid-span to avoid per-day math), so a month picked here estimates an
    unspecified day within it without biasing every planning date early -- and a literal 15th is used
    (not a computed true midpoint) to keep clear of month-length unevenness. Defaults to
    `MonthDateInput`; pass `context` through to tune the picker's range."""

    CANONICAL_DAY = 15

    def __init__( self, *, context = AppConst.DATE_CONTEXT_FUTURE, widget = None, **kwargs ):
        widget = widget or MonthDateInput( context = context )
        super().__init__( input_formats = [ MonthDateInput.FORMAT ], widget = widget, **kwargs )

    def to_python( self, value ):
        parsed = super().to_python( value )
        # `YYYY-MM` parses to the 1st; snap to the canonical mid-month day. Blank stays None.
        return parsed if parsed is None else parsed.replace( day = self.CANONICAL_DAY )
