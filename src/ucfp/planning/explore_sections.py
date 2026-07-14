"""Explore's curated section views -- one compact form per input section, over the working scenario.

Each input section has its own data shape, so each gets its own small view here rather than a generic
grid. Phase 2 ships two: `LivingExpensesExploreForm` (the discretionary spending at a chosen age band)
and `EconomicAssumptionsExploreForm` (the headline rates). Both read the working `Scenario` and return an
updated one from `apply`, touching only their curated fields and leaving the rest of the inputs intact --
the full editors remain the way to reach everything else.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.rate import Rate
from common.recurrence import TimeUnit

from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import Plans

# The discretionary expenses surfaced in Explore (catalog handle -> label), the big variable items.
_CURATED_EXPENSES = [
    ( 'vacations', 'Vacations' ),
    ( 'travel', 'Travel' ),
    ( 'dining-out', 'Dining out' ),
    ( 'medical-expenses', 'Medical' ),
]

# The headline economic rates surfaced in Explore (EconomicParameters attr -> label).
_CURATED_RATES = [
    ( 'inflation', 'Inflation' ),
    ( 'stock_appreciation', 'Stock growth' ),
    ( 'bond_appreciation', 'Bond growth' ),
    ( 'retirement_growth', 'Retirement-account growth' ),
]

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
    """The Living Expenses section view: the curated discretionary expenses at the selected age band,
    one editable value each. The band (an index into the shared `expense_spans` timeline) targets which
    band the rows show and write; `apply` updates only those bands' amounts, preserving the other bands
    and every non-curated expense."""

    def __init__( self, data = None, *, scenario = None, band = 0 ):
        super().__init__( data )
        self._plans = scenario.plans if scenario is not None else Plans()
        spans       = self._plans.expense_spans or [ None ]
        self._band  = max( 0, min( band, len( spans ) - 1 ) )
        by_handle   = { expense.handle : expense for expense in self._plans.recurring_expenses }
        self._rows  = list()
        for handle, label in _CURATED_EXPENSES:
            expense = by_handle.get( handle )
            if expense is None:                        # a complete plan carries them, but stay defensive
                continue
            field         = forms.DecimalField( required = False, min_value = 0, label = label )
            field.initial = self._amount( expense, self._band )
            field.widget.attrs[ 'class' ] = 'form-control form-control-sm'
            self.fields[ handle ] = field
            self._rows.append( { 'label' : label, 'field' : self[ handle ],
                                 'cadence' : _cadence_hint( expense.interval ) } )

    @staticmethod
    def _amount( expense, band : int ):
        amounts = expense.amounts or []
        if band < len( amounts ):
            return amounts[ band ]
        return amounts[ -1 ] if amounts else None

    @property
    def band( self ) -> int:
        return self._band

    @property
    def rows( self ) -> list:
        return self._rows

    @property
    def bands( self ) -> list:
        """The band options for the selector -- each an index and its age-range label."""
        return [ { 'index' : index, 'label' : label }
                 for index, label in enumerate( _band_labels( self._plans.expense_spans or [ None ] ) ) ]

    def apply( self, scenario ):
        cleaned = self.cleaned_data
        updated = list()
        for expense in self._plans.recurring_expenses:
            value = cleaned.get( expense.handle )
            if ( expense.handle in self.fields ) and ( value is not None ):
                amounts = list( expense.amounts )
                while len( amounts ) <= self._band:    # pad a short list up to the edited band
                    amounts.append( amounts[ -1 ] if amounts else Decimal( '0' ) )
                amounts[ self._band ] = value
                updated.append( replace( expense, amounts = amounts ) )
            else:
                updated.append( expense )
        return replace( scenario, plans = replace( self._plans, recurring_expenses = updated ) )


class EconomicAssumptionsExploreForm( forms.Form ):
    """The Economic Assumptions section view: the headline rates as percentages. `apply` writes them back
    onto the assumptions' `EconomicParameters`, leaving its other rates and the window intact."""

    def __init__( self, data = None, *, scenario = None ):
        super().__init__( data )
        self._assumptions = scenario.assumptions if scenario is not None else Assumptions()
        economics   = self._assumptions.economics
        self._rows  = list()
        for attr, label in _CURATED_RATES:
            field         = forms.DecimalField( required = False, label = label )
            field.initial = ( getattr( economics, attr ).fraction * 100 ) if economics is not None else None
            field.widget.attrs.update( { 'class' : 'form-control form-control-sm', 'step' : '0.1' } )
            self.fields[ attr ] = field
            self._rows.append( { 'label' : label, 'field' : self[ attr ] } )

    @property
    def rows( self ) -> list:
        return self._rows

    def apply( self, scenario ):
        economics = self._assumptions.economics
        if economics is None:
            return scenario
        cleaned = self.cleaned_data
        changes = { attr : Rate.percent( cleaned[ attr ] )
                    for attr, _label in _CURATED_RATES if cleaned.get( attr ) is not None }
        return replace(
            scenario, assumptions = replace( self._assumptions, economics = replace( economics, **changes ) ) )
