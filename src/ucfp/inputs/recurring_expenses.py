"""Living Expenses -- the household's regular (non-property, non-vehicle) recurring costs.

The step presents the applicable catalog categories (everyday, discretionary, health, miscellaneous)
as a table over a shared age-span timeline, so a level can rise or fall with age. This module seeds
those expenses from the catalog (preserving amounts already set) and drives the self-saving table.
Vehicle running costs are a separate, per-car model in the Vehicle Expenses step.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from ucfp.environment.constants import AppConst
from ucfp.parameter_sets.enums import ExpenseClass
from ucfp.inputs.plans.schemas import RecurringExpense
from ucfp.inputs.cadence import (
    add_cadence_fields, add_calculator_fields, cadence_cells, calculator_cells, per_year, read_cadence,
    read_durable )
from ucfp.inputs.expenses import grouped_sections, kept_attr, kept_interval, ordered_catalog


def merged_recurring_expenses( profile, plans ) -> list:
    """The `LIVING`-class catalog expenses as `RecurringExpense`s -- the always-apply household costs --
    existing amounts (and any chosen cadence) preserved, missing ones seeded at the catalog default
    across every span. The category, personal tax class, and realization are re-derived each merge (not
    user edits)."""
    span_count = len( plans.expense_spans ) if plans and plans.expense_spans else 1
    existing   = { expense.name: expense
                   for expense in plans.recurring_expenses } if plans else dict()
    merged = list()
    for catalog_expense in ordered_catalog():
        if catalog_expense.expense_class is not ExpenseClass.LIVING:
            continue
        prior = existing.get( catalog_expense.name )
        merged.append( RecurringExpense(
            name = catalog_expense.name, category = catalog_expense.category,
            expense_tax_class = catalog_expense.expense_tax_class,
            amounts = _aligned_amounts( prior, catalog_expense.default_amount, span_count ),
            interval = kept_interval( prior, catalog_expense ),
            realization = catalog_expense.realization,
            cadence_domain = catalog_expense.cadence_domain,
            count = kept_attr( prior, catalog_expense, 'count' ),
            cost_each = kept_attr( prior, catalog_expense, 'cost_each' ),
            lifespan = kept_attr( prior, catalog_expense, 'lifespan' ) ) )
    return merged


def _aligned_amounts( prior, default : Decimal, span_count : int ) -> list:
    """`prior`'s amounts padded (with its last) or truncated to `span_count`, or the catalog `default`
    across every span when there is no prior expense."""
    if prior is None:
        return [ default ] * span_count
    amounts = list( prior.amounts )
    if len( amounts ) < span_count:
        amounts += [ amounts[ -1 ] if amounts else default ] * ( span_count - len( amounts ) )
    return amounts[ :span_count ]


class RecurringExpensesForm( forms.Form ):
    """The recurring-expenses table: rows are the `LIVING`-class expenses grouped by category, columns
    are the spans of the shared timeline. Each span carries an "until age" (the last blank, the
    open "thereafter" span); each cell is an amount at the row's cadence. Filling the open span's age
    splits it (a new open span duplicates it); clearing a span's age deletes that span. Ages are the
    primary subject's. `apply` writes the shared `expense_spans` and every recurring expense's per-span
    amounts; `spans_changed` reports when the span set changed, so the pane re-renders."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._birthdate = ( profile.subjects[ 0 ].birthdate
                            if profile is not None and profile.subjects else None )
        self._expenses  = merged_recurring_expenses( profile, plans )
        self._spans     = list( plans.expense_spans ) if plans and plans.expense_spans else [ None ]
        for si, until in enumerate( self._spans ):
            field = forms.IntegerField( required = False, min_value = 0 )
            field.initial = until
            self.fields[ self._until_key( si ) ] = field
        for ei, expense in enumerate( self._expenses ):
            add_cadence_fields( self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain )
            durable = expense.count is not None
            if durable:                                    # a durable's amount is filled by the calculator
                add_calculator_fields( self, ei, expense.count, expense.cost_each, expense.lifespan )
            for si in range( len( self._spans ) ):
                cell = forms.DecimalField( required = False, min_value = 0 )
                cell.initial = expense.amounts[ si ] if si < len( expense.amounts ) else (
                    expense.amounts[ -1 ] if expense.amounts else None )
                if durable:
                    cell.widget.attrs[ 'readonly' ] = True
                    cell.widget.attrs[ 'class' ] = AppConst.CALC_TARGET_CLASS
                self.fields[ self._amount_key( ei, si ) ] = cell

    @staticmethod
    def _until_key( si : int ) -> str:
        return f'until_{si}'

    @staticmethod
    def _amount_key( ei : int, si : int ) -> str:
        return f'amt_{ei}_{si}'

    @staticmethod
    def _cad_prefix( ei : int ) -> str:
        return f'cad_{ei}'

    @property
    def span_count( self ) -> int:
        return len( self._spans )

    @property
    def span_headers( self ) -> list:
        """The 'until age' header field per span, with the calendar year the primary reaches that age
        (when a birthdate is known) -- the last span's age is blank (the open 'thereafter')."""
        headers = list()
        for si, until in enumerate( self._spans ):
            year = ( self._birthdate.year + until
                     if until is not None and self._birthdate is not None else None )
            headers.append( { 'field': self[ self._until_key( si ) ], 'year': year } )
        return headers

    @property
    def sections( self ) -> list:
        """The expense rows grouped into ordered category sections (a header per category), in the shared
        deliberate (group, item) order. Each row is its name, cadence, and one amount cell per span; a
        durable row's span amounts are filled by its `calculator` (count x cost-each, age-flat) and its
        cadence shows read-only."""
        return grouped_sections(
            ( expense.category, self._row( ei, expense ) )
            for ei, expense in enumerate( self._expenses ) )

    def _row( self, ei : int, expense ) -> dict:
        durable = expense.count is not None
        return {
            'name'        : expense.name,
            'cadence'     : cadence_cells(
                self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain ),
            'count_entry' : durable,
            'calculator'  : ( calculator_cells(
                self, ei, per_year( expense.amounts[ 0 ] if expense.amounts else None, expense.interval ) )
                if durable else None ),
            'cells'       : [ self[ self._amount_key( ei, si ) ]
                              for si in range( len( self._spans ) ) ] }

    def apply( self, profile, plans ):
        columns  = self._columns()
        spans    = [ until for until, _ in columns ]
        expenses = [ self._edited( ei, expense, columns ) for ei, expense in enumerate( self._expenses ) ]
        return profile, replace( plans, expense_spans = spans, recurring_expenses = expenses )

    def _edited( self, ei : int, expense, columns : list ):
        """`expense` with its cadence from this row's fields and its per-span amounts re-read from the
        columns. A durable's amount is computed from its calculator (count x cost-each) and applied
        age-flat to every span; its count/cost-each are remembered."""
        interval = read_cadence( self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain )
        if expense.count is not None:
            amount, count, cost_each, lifespan = read_durable( self, ei )
            # An incomplete calculator charges nothing; `amounts` is non-Optional, so that reads as 0
            # here (the PropertyExpense default_amount, which is Optional, stores None for the same case).
            total = amount if amount is not None else Decimal( '0' )
            return replace( expense, interval = interval, amounts = [ total ] * len( columns ),
                            count = count, cost_each = cost_each, lifespan = lifespan )
        return replace(
            expense, interval = interval, amounts = [ amounts[ ei ] for _, amounts in columns ] )

    def spans_changed( self ) -> bool:
        """Whether the applied span timeline differs from the current one -- a span added, removed, or
        re-aged -- so the pane must re-render; a pure amount edit leaves it unchanged (a silent save)."""
        return [ until for until, _ in self._columns() ] != list( self._spans )

    def _columns( self ) -> list:
        """The edited (until_age, [amount per expense]) columns after this POST's one structural action,
        if any: an explicit column delete (a row's x) or splitting the open span (giving it an age).
        The last column is always the open 'thereafter' span -- deleting the open span leaves the new
        last ageless (so it becomes the thereafter). A non-last span left ageless is dropped, keeping
        the timeline continuous. Ordered by age, the open span last."""
        cleaned = self.cleaned_data
        columns = [ [ cleaned.get( self._until_key( si ) ),
                      [ cleaned.get( self._amount_key( ei, si ) ) or Decimal( '0' )
                        for ei in range( len( self._expenses ) ) ] ]
                    for si in range( len( self._spans ) ) ]
        delete = self._delete_index()
        if delete is not None and 0 <= delete < len( columns ):
            del columns[ delete ]                          # the row's x control
        elif columns and columns[ -1 ][ 0 ] is not None:
            columns.append( [ None, list( columns[ -1 ][ 1 ] ) ] )   # split the open span
        if not columns:
            columns = [ [ None, [ Decimal( '0' ) ] * len( self._expenses ) ] ]
        columns[ -1 ][ 0 ] = None                          # the last span is always the open one
        kept = [ ( until, amounts ) for index, ( until, amounts ) in enumerate( columns )
                 if until is not None or index == len( columns ) - 1 ]
        kept.sort( key = lambda column: ( column[ 0 ] is None, column[ 0 ] or 0 ) )
        return kept

    def _delete_index( self ):
        """The span index the row's x control asked to delete (a raw `delete_span` field, not a form
        field), or None when this save carried no delete."""
        try:
            return int( ( self.data or {} ).get( 'delete_span' ) )
        except ( TypeError, ValueError ):
            return None
