"""The per-expense cadence control shared by the Home and Living expense tables.

An expense's cadence is a magnitude + unit ("Every N units") the user may edit within its
`CadenceDomain` -- `FIXED` shows a static label (amount only), the others offer a magnitude field and a
unit choice. This module builds and reads those form fields and formats a cadence for display, so both
tables drive the control the same way.
"""
from decimal import Decimal
from typing import Optional

from django import forms

from common.forms import MoneyField
from common.recurrence import Duration, TimeUnit

from ucfp.parameter_sets.enums import CadenceDomain

_MAX_MAGNITUDE = 50

# The units each editable domain offers, in display order; `FIXED` offers none (not editable).
_UNITS_BY_DOMAIN = {
    CadenceDomain.FIXED    : (),
    CadenceDomain.WK_MO    : ( TimeUnit.WEEK, TimeUnit.MONTH ),
    CadenceDomain.MO_YR    : ( TimeUnit.MONTH, TimeUnit.YEAR ),
    CadenceDomain.WK_MO_YR : ( TimeUnit.WEEK, TimeUnit.MONTH, TimeUnit.YEAR ),
    CadenceDomain.N_YEARS  : ( TimeUnit.YEAR, ),
}


def cadence_units( domain ) -> tuple:
    return _UNITS_BY_DOMAIN[ domain ]


def is_editable( domain ) -> bool:
    """Whether the user may re-select this domain's cadence (every domain but `FIXED`)."""
    return bool( _UNITS_BY_DOMAIN[ domain ] )


def per_year( amount : Optional[ Decimal ], interval : Optional[ Duration ] ) -> Decimal:
    """A per-cadence amount as a whole-dollar yearly figure -- the durable calculator's advisory readout,
    annualizing the (authoritative) per-band amount for the "~ $N/yr" preview."""
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
    magnitude.widget.attrs[ 'aria-label' ] = 'Cadence magnitude'
    magnitude.widget.attrs[ 'class' ]      = 'form-control form-control-sm input-count'
    form.fields[ _count_key( prefix ) ] = magnitude
    unit = forms.ChoiceField( required = False, choices = [ ( u.name, u.label ) for u in units ] )
    unit.initial = interval.unit.name if interval is not None else units[ 0 ].name
    unit.widget.attrs[ 'aria-label' ] = 'Cadence unit'
    unit.widget.attrs[ 'class' ]      = 'custom-select custom-select-sm cadence-unit'
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


def add_optional_cadence_fields( form, prefix, interval, domain ) -> None:
    """Like `add_cadence_fields`, but the magnitude may be left blank to mean *no* recurrence (a one-time
    plan). Seeded from `interval` when recurring, else a blank magnitude with the unit defaulting to the
    domain's coarsest (a one-time plan reads as "every [ ] years"). A no-op for a `FIXED` domain."""
    units = cadence_units( domain )
    if not units:
        return
    magnitude = forms.IntegerField( required = False, min_value = 1, max_value = _MAX_MAGNITUDE )
    magnitude.initial = interval.count if interval is not None else None      # blank -> one-time
    magnitude.widget.attrs[ 'aria-label' ] = 'Cadence magnitude'
    magnitude.widget.attrs[ 'class' ]      = 'form-control form-control-sm input-count'
    form.fields[ _count_key( prefix ) ] = magnitude
    unit = forms.ChoiceField( required = False, choices = [ ( u.name, u.label ) for u in units ] )
    unit.initial = interval.unit.name if interval is not None else units[ -1 ].name
    unit.widget.attrs[ 'aria-label' ] = 'Cadence unit'
    unit.widget.attrs[ 'class' ]      = 'custom-select custom-select-sm cadence-unit'
    form.fields[ _unit_key( prefix ) ] = unit


def read_optional_cadence( form, prefix, domain ):
    """The interval for an optional-cadence row: `None` when the magnitude is left blank (a one-time
    plan), else `Duration(magnitude, unit)`. A blank unit falls back to the domain's coarsest."""
    units = cadence_units( domain )
    if not units:
        return None
    cleaned = form.cleaned_data
    count   = cleaned.get( _count_key( prefix ) )
    if not count:
        return None
    unit_name = cleaned.get( _unit_key( prefix ) ) or units[ -1 ].name
    return Duration( count, TimeUnit[ unit_name ] )


# ----- The durable "count-entry" calculator (a shared control on both expense tables) -----
# A durable expense's amount is entered directly per band, like any other expense; the calculator is an
# optional helper that estimates an annual figure -- `count` items at `cost_each`, replaced every
# `lifespan` years -- and fills the bands on demand. Its three inputs are remembered on the expense only
# to repopulate the calculator when it is reopened; the amount is authoritative and never recomputed from
# them. Both tables build, view, and read the calculator through these helpers so they behave alike.

def add_calculator_fields( form, prefix, count : Optional[ int ], cost_each : Optional[ Decimal ],
                           lifespan : Optional[ int ] ) -> None:
    """Add a durable's calculator inputs -- item count, cost-each, and replacement lifespan (years) --
    seeded from the remembered breakdown. `prefix` namespaces the three field names within the form."""
    count_field = forms.IntegerField( required = False, min_value = 1 )
    count_field.initial = count
    count_field.widget.attrs[ 'aria-label' ] = 'Item count'
    count_field.widget.attrs[ 'class' ]      = 'form-control form-control-sm input-count'
    form.fields[ _calc_count_key( prefix ) ] = count_field
    cost_field = MoneyField( required = False, min_value = 0 )
    cost_field.initial = cost_each
    cost_field.widget.attrs[ 'aria-label' ] = 'Cost each'
    form.fields[ _calc_cost_key( prefix ) ] = cost_field
    lifespan_field = forms.IntegerField( required = False, min_value = 1, max_value = 100 )
    lifespan_field.initial = lifespan
    lifespan_field.widget.attrs[ 'aria-label' ] = 'Replacement lifespan (years)'
    lifespan_field.widget.attrs[ 'class' ]      = 'form-control form-control-sm input-count'
    form.fields[ _calc_lifespan_key( prefix ) ] = lifespan_field


def calculator_cells( form, prefix, per_year_amount : Decimal ) -> dict:
    """The template's view of a durable row's calculator: its three bound fields, plus the seeded annual
    cost for the initial (pre-JS) readout."""
    return {
        'count'    : form[ _calc_count_key( prefix ) ],
        'cost'     : form[ _calc_cost_key( prefix ) ],
        'lifespan' : form[ _calc_lifespan_key( prefix ) ],
        'per_year' : per_year_amount }


def read_calculator_inputs( form, prefix ) -> tuple:
    """A durable's remembered calculator inputs -- (count, cost_each, lifespan) -- read back from its
    fields. The amount is no longer derived from these (it is entered directly per band); the inputs are
    kept only to repopulate the calculator when it is reopened."""
    cleaned = form.cleaned_data
    return ( cleaned.get( _calc_count_key( prefix ) ),
             cleaned.get( _calc_cost_key( prefix ) ),
             cleaned.get( _calc_lifespan_key( prefix ) ) )


def _count_key( prefix ) -> str:
    return f'{prefix}_count'


def _unit_key( prefix ) -> str:
    return f'{prefix}_unit'


def _calc_count_key( prefix ) -> str:
    return f'count_{prefix}'


def _calc_cost_key( prefix ) -> str:
    return f'cost_{prefix}'


def _calc_lifespan_key( prefix ) -> str:
    return f'lifespan_{prefix}'
