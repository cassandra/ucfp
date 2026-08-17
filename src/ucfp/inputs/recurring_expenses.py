"""Living Expenses -- the household's `LIVING`-class recurring costs (the always-apply household costs).

The step presents the `LIVING`-class catalog expenses, grouped by category, as a table over a shared
age-span timeline, so a level can rise or fall with age. This module seeds those expenses from the
catalog (preserving amounts already set) and drives the self-saving table. Vehicle running costs are a
separate, per-car model in the Vehicle plan step.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField

from ucfp.environment.constants import AppConst
from ucfp.parameter_sets.enums import ExpenseClass
from ucfp.inputs.plans.schemas import RecurringExpense
from ucfp.inputs.cadence import (
    add_cadence_fields, add_calculator_fields, cadence_cells, calculator_cells, per_year, read_cadence,
    read_calculator_inputs )
from ucfp.inputs.expense_totals import ExpenseTotalsMatrix, annualized_sum
from ucfp.inputs.expenses import grouped_sections, kept_attr, kept_interval, ordered_catalog


def merged_recurring_expenses( profile, plans ) -> list:
    """The `LIVING`-class catalog expenses as `RecurringExpense`s -- the always-apply household costs --
    existing amounts (and any chosen cadence) preserved, missing ones seeded at the catalog default
    across every span. The category, personal tax class, and realization are re-derived each merge (not
    user edits)."""
    span_count = len( plans.expense_spans ) if plans and plans.expense_spans else 1
    existing   = { expense.handle: expense
                   for expense in plans.recurring_expenses } if plans else dict()
    merged = list()
    for catalog_expense in ordered_catalog():
        if catalog_expense.expense_class is not ExpenseClass.LIVING:
            continue
        prior = existing.get( catalog_expense.handle )
        merged.append( RecurringExpense(
            name = catalog_expense.name, handle = catalog_expense.handle,
            category = catalog_expense.category,
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


class RecurringExpensesForm( ExpenseTotalsMatrix, forms.Form ):
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
            field.widget.attrs[ 'class' ] = 'form-control form-control-sm input-count'   # at most 3 digits
            self.fields[ self._until_key( si ) ] = field
        for ei, expense in enumerate( self._expenses ):
            add_cadence_fields( self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain )
            durable = expense.count is not None
            if durable:                                    # a durable also carries an optional calculator
                add_calculator_fields( self, ei, expense.count, expense.cost_each, expense.lifespan )
            for si in range( len( self._spans ) ):
                cell = MoneyField( required = False, min_value = 0 )
                cell.initial = self._span_amount( expense, si )
                cell.widget.attrs[ 'class' ] += f' {AppConst.SPAN_AMOUNT_CLASS}'   # scanned for changes
                if durable:                                # editable; the calculator fills it on demand
                    cell.widget.attrs[ 'class' ] += f' {AppConst.CALC_TARGET_CLASS}'
                    cell.widget.attrs[ f'data-{AppConst.CALC_DATA_ATTR}' ] = str( ei )
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
            headers.append( { 'field': self[ self._until_key( si ) ], 'year': year,
                              'open': until is None } )
        return headers

    _TOTALS_PREFIX = 'living'

    @property
    def sections( self ) -> list:
        """The expense rows grouped into ordered category sections (a header per category), in the shared
        deliberate (group, item) order. Each row is its name, cadence, and one amount cell per span; a
        durable row's span amounts are directly editable and may vary by band, with an optional
        `calculator` that fills them on demand. Each section also carries its per-span annual
        `subtotals` (one figure per span column), shown on the category header."""
        return self.attach_subtotals( grouped_sections(
            ( expense.category, self._row( ei, expense ) )
            for ei, expense in enumerate( self._expenses ) ) )

    # -- the totals-matrix primitives: rows are the living expenses, columns are the age-span bands ----
    def _total_rows( self ) -> list:
        return self._expenses

    def _total_columns( self ) -> int:
        return self.span_count

    def _column_sum( self, expenses, si : int ) -> Decimal:
        """The annual sum of `expenses` at span `si`: each row's shown amount annualized and summed."""
        return annualized_sum(
            ( self._span_amount( expense, si ), expense.interval ) for expense in expenses )

    def _row( self, ei : int, expense ) -> dict:
        durable = expense.count is not None
        cells   = self._cells( ei, expense )
        uniform = not any( cell[ 'changed' ] for cell in cells )   # no per-band variation to protect
        return {
            'name'        : expense.name,
            'calc_id'     : ei,
            'cadence'     : cadence_cells(
                self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain ),
            'count_entry' : durable,
            'calculator'  : ( calculator_cells(
                self, ei, per_year( expense.amounts[ 0 ] if expense.amounts else None, expense.interval ),
                autofill = uniform )
                if durable else None ),
            'cells'       : cells }

    def _cells( self, ei : int, expense ) -> list:
        """One amount cell per span, each flagged when its shown value differs from the previous span's
        -- a step up or down -- so a reader can scan which expenses change with age. The first span is
        the baseline (never flagged); durables vary by band like any other row, so they flag too."""
        cells    = list()
        previous = None
        for si in range( len( self._spans ) ):
            amount    = self._span_amount( expense, si )
            direction = None
            if previous is not None and amount is not None and amount != previous:
                direction = 'up' if amount > previous else 'down'
            cells.append( { 'field'     : self[ self._amount_key( ei, si ) ],
                            'changed'   : direction is not None,
                            'direction' : direction } )
            previous = amount
        return cells

    @staticmethod
    def _span_amount( expense, si : int ):
        """The amount shown for span `si`: its own per-span value, or the last available when the span
        list runs short (so a padded span reads as its predecessor, not as a change)."""
        if si < len( expense.amounts ):
            return expense.amounts[ si ]
        return expense.amounts[ -1 ] if expense.amounts else None

    def apply( self, profile, plans ):
        columns  = self._columns()
        spans    = [ until for until, _ in columns ]
        expenses = [ self._edited( ei, expense, columns ) for ei, expense in enumerate( self._expenses ) ]
        return profile, replace( plans, expense_spans = spans, recurring_expenses = expenses )

    def _edited( self, ei : int, expense, columns : list ):
        """`expense` with its cadence from this row's fields and its per-span amounts re-read from the
        columns -- authoritative, just like a normal row (per-age variation comes for free). A durable
        additionally remembers its calculator inputs (count/cost-each/lifespan), which do not drive the
        amount -- they only repopulate the calculator when it is reopened."""
        interval = read_cadence( self, self._cad_prefix( ei ), expense.interval, expense.cadence_domain )
        amounts  = [ column_amounts[ ei ] for _, column_amounts in columns ]
        if expense.count is not None:
            count, cost_each, lifespan = read_calculator_inputs( self, ei )
            return replace( expense, interval = interval, amounts = amounts,
                            count = count, cost_each = cost_each, lifespan = lifespan )
        return replace( expense, interval = interval, amounts = amounts )

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
