"""Explore's curated section views -- one compact form per input section, over the working scenario.

Each input section has its own data shape, so each gets its own small view here rather than a generic
grid. Phase 2 ships two: `LivingExpensesExploreForm` (every recurring expense's amount, a grid of
expenses by age band) and `EconomicAssumptionsExploreForm` (every economic rate). Both render the
*full* set of that section's inputs -- Explore is for exploring value changes, so the whole section is
editable -- read the working `Scenario`, and return an updated one from `apply`, touching only their own
values (amounts / rates) and leaving structure (cadence, durable items, age spans, the window) intact.

The `_DEFAULT_*` sets below name the inputs shown by default before the user curates which to focus on;
the section still renders every input, so a curation layer only toggles visibility.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField, PercentField
from common.rate import Rate
from common.recurrence import TimeUnit

from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.external_factors import ECONOMIC_FACTORS
from ucfp.inputs.plans.schemas import Plans

# The inputs shown by default in each Explore section before the user curates the set -- the big variable
# "what-if" items. The section renders every input regardless; these are only the initial selection.
_DEFAULT_EXPENSE_HANDLES = ( 'vacations', 'travel', 'dining-out', 'medical-expenses' )
_DEFAULT_RATE_FIELDS     = ( 'inflation', 'stock_appreciation', 'bond_appreciation', 'retirement_growth' )

_UNIT_ABBREV = { 'DAY': 'day', 'WEEK': 'wk', 'MONTH': 'mo', 'YEAR': 'yr' }


def _cadence_hint( interval ) -> str:
    """A compact per-period hint for an expense's cadence -- `/yr`, `/wk`, `/qtr`, `/3 mo`."""
    if interval.count == 3 and interval.unit is TimeUnit.MONTH:
        return '/qtr'
    abbrev = _UNIT_ABBREV.get( interval.unit.name, interval.unit.name.lower() )
    return f'/{abbrev}' if interval.count == 1 else f'/{interval.count} {abbrev}'


def _band_labels( spans : list ) -> list:
    """Age-range labels for the shared expense-span timeline. `spans` are until-ages; the last (None) is
    the open "thereafter" band. A single `[None]` span is one all-ages band."""
    if not spans or spans == [ None ]:
        return [ 'All ages' ]
    labels, previous = list(), None
    for until in spans:
        if until is None:
            labels.append( f'{previous}+' if previous is not None else 'All ages' )
        elif previous is None:
            labels.append( f'Now–{until}' )
        else:
            labels.append( f'{previous}–{until}' )
        previous = until
    return labels


class LivingExpensesExploreForm( forms.Form ):
    """The Living Expenses section view: every recurring expense's amount across every age band, one
    editable value per expense per band. Rows are the expenses, columns the bands. `apply` writes every
    band's amount back, value-only -- each expense's cadence, durable-item structure, and the age spans
    stay as the full editor set them."""

    def __init__( self, data = None, *, scenario = None, selected = None ):
        super().__init__( data )
        self._plans = scenario.plans if scenario is not None else Plans()
        self._bands = _band_labels( self._plans.expense_spans or [ None ] )
        chosen      = set( selected ) if selected is not None else set( _DEFAULT_EXPENSE_HANDLES )
        self._rows  = list()
        for expense in self._plans.recurring_expenses:
            cells = list()
            for band in range( len( self._bands ) ):
                name          = self._field_name( expense.handle, band )
                field         = MoneyField( required = False, min_value = 0, label = expense.name )
                field.initial = self._amount( expense, band )
                self.fields[ name ] = field
                cells.append( self[ name ] )
            self._rows.append( { 'handle' : expense.handle, 'label' : expense.name, 'cells' : cells,
                                 'cadence' : _cadence_hint( expense.interval ),
                                 'selected' : expense.handle in chosen } )

    @staticmethod
    def _field_name( handle : str, band : int ) -> str:
        return f'{handle}__{band}'

    @staticmethod
    def _amount( expense, band : int ):
        amounts = expense.amounts or []
        if band < len( amounts ):
            return amounts[ band ]
        return amounts[ -1 ] if amounts else None

    @property
    def rows( self ) -> list:
        return self._rows

    @property
    def bands( self ) -> list:
        """The column headers -- one age-range label per band."""
        return self._bands

    def apply( self, scenario ):
        cleaned = self.cleaned_data
        updated = list()
        for expense in self._plans.recurring_expenses:
            amounts = list( expense.amounts )
            while len( amounts ) < len( self._bands ):      # pad a short list up to every shown band
                amounts.append( amounts[ -1 ] if amounts else Decimal( '0' ) )
            for band in range( len( self._bands ) ):
                value = cleaned.get( self._field_name( expense.handle, band ) )
                if value is not None:
                    amounts[ band ] = value
            updated.append( replace( expense, amounts = amounts ) )
        return replace( scenario, plans = replace( self._plans, recurring_expenses = updated ) )


class EconomicAssumptionsExploreForm( forms.Form ):
    """The Economic Assumptions section view: every economic rate as a percentage (the same fields and
    labels as the full external-factors editor). `apply` writes them back onto the assumptions'
    `EconomicParameters`, leaving the window and non-rate fields intact."""

    def __init__( self, data = None, *, scenario = None, selected = None ):
        super().__init__( data )
        self._assumptions = scenario.assumptions if scenario is not None else Assumptions()
        economics   = self._assumptions.economics
        chosen      = set( selected ) if selected is not None else set( _DEFAULT_RATE_FIELDS )
        self._rows  = list()
        for factor in ECONOMIC_FACTORS:
            field         = PercentField( required = False, label = factor.label )
            field.initial = ( getattr( economics, factor.field ).fraction * 100 ) if economics is not None else None
            self.fields[ factor.field ] = field
            self._rows.append( { 'handle' : factor.field, 'label' : factor.label, 'field' : self[ factor.field ],
                                 'selected' : factor.field in chosen } )

    @property
    def rows( self ) -> list:
        return self._rows

    def apply( self, scenario ):
        economics = self._assumptions.economics
        if economics is None:
            return scenario
        cleaned = self.cleaned_data
        changes = { factor.field : Rate.percent( cleaned[ factor.field ] )
                    for factor in ECONOMIC_FACTORS if cleaned.get( factor.field ) is not None }
        return replace(
            scenario, assumptions = replace( self._assumptions, economics = replace( economics, **changes ) ) )
