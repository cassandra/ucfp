"""The per-expense cadence control shared by the Home and Living expense tables.

An expense's cadence is a magnitude + unit ("Every N units") the user may edit within its
`CadenceDomain` -- `FIXED` shows a static label (amount only), the others offer a magnitude field and a
unit choice. This module builds and reads those form fields and formats a cadence for display, so both
tables drive the control the same way.
"""
from decimal import Decimal

from django import forms

from common.recurrence import Duration, TimeUnit

from ucfp.parameter_sets.enums import CadenceDomain

_MAX_MAGNITUDE = 50

# The units each editable domain offers, in display order; `FIXED` offers none (not editable).
_UNITS_BY_DOMAIN = {
    CadenceDomain.FIXED   : (),
    CadenceDomain.WK_MO   : ( TimeUnit.WEEK, TimeUnit.MONTH ),
    CadenceDomain.MO_YR   : ( TimeUnit.MONTH, TimeUnit.YEAR ),
    CadenceDomain.N_YEARS : ( TimeUnit.YEAR, ),
}


def cadence_units( domain ) -> tuple:
    return _UNITS_BY_DOMAIN[ domain ]


def is_editable( domain ) -> bool:
    """Whether the user may re-select this domain's cadence (every domain but `FIXED`)."""
    return bool( _UNITS_BY_DOMAIN[ domain ] )


def durable_amount( count, cost_each, lifespan ):
    """A durable's annualized amount -- count x cost-each / lifespan -- or None when any input is missing
    (non-blocking: an incomplete calculator charges nothing)."""
    if count is None or cost_each is None or not lifespan:
        return None
    return count * cost_each / lifespan


def per_year( amount, interval ) -> Decimal:
    """A per-cadence amount as a whole-dollar yearly figure -- the durable calculator's advisory readout
    (count x cost-each is a per-cycle total; this annualizes it)."""
    if amount is None or interval is None:
        return Decimal( 0 )
    return ( amount * interval.occurrences_per_year() ).quantize( Decimal( 1 ) )


def cadence_label( interval ) -> str:
    """A cadence as "every N units" for display -- the singular "every week" for a count of one."""
    if interval is None:
        return 'every year'
    if interval.count == 1:
        return f'every {interval.unit.label.lower()}'
    return f'every {interval.count} {interval.unit.label.lower()}s'


def add_cadence_fields( form, prefix, interval, domain ) -> None:
    """Add the magnitude + unit fields for an editable-cadence row (a no-op for a `FIXED` domain),
    seeded from the current interval. `prefix` namespaces the two field names within the form."""
    units = cadence_units( domain )
    if not units:
        return
    magnitude = forms.IntegerField( required = False, min_value = 1, max_value = _MAX_MAGNITUDE )
    magnitude.initial = interval.count if interval is not None else 1
    form.fields[ _count_key( prefix ) ] = magnitude
    unit = forms.ChoiceField( required = False, choices = [ ( u.name, u.label ) for u in units ] )
    unit.initial = interval.unit.name if interval is not None else units[ 0 ].name
    form.fields[ _unit_key( prefix ) ] = unit


def cadence_cells( form, prefix, interval, domain ) -> dict:
    """The template's view of a row's cadence: `editable` plus either the two bound fields (editable) or
    the static `label` (`FIXED`)."""
    if not is_editable( domain ):
        return { 'editable': False, 'label': cadence_label( interval ) }
    return { 'editable': True, 'count': form[ _count_key( prefix ) ], 'unit': form[ _unit_key( prefix ) ] }


def read_cadence( form, prefix, interval, domain ):
    """The interval after this edit: the chosen magnitude/unit for an editable row, else the unchanged
    seed. A blank field falls back to the seed (non-blocking)."""
    units = cadence_units( domain )
    if not units:
        return interval
    cleaned   = form.cleaned_data
    count     = cleaned.get( _count_key( prefix ) ) or ( interval.count if interval else 1 )
    unit_name = cleaned.get( _unit_key( prefix ) ) or ( interval.unit.name if interval else units[ 0 ].name )
    return Duration( count, TimeUnit[ unit_name ] )


def _count_key( prefix ) -> str:
    return f'{prefix}_count'


def _unit_key( prefix ) -> str:
    return f'{prefix}_unit'
