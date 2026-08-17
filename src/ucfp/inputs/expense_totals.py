"""Server-computed totals for the interview spending panes.

The server is the source of truth: after each expense edit the pane re-reads the persisted plans,
folds the amounts into a whole-dollar **yearly** figure, and pushes the result back to the page via an
antinode `replace_map`. This module holds the shared pieces every spending pane's totals build on --
the cadence-normalizing fold, the on-page total descriptor, and the fragment renderer. Each pane
assembles its own set of totals on top (a single per-vehicle total, a per-span-column set for Living, a
per-property-column set for Home).

Amounts are stored per-occurrence at each row's own cadence (weekly / monthly / annual / multi-year), so
they are annualized via `per_year` before summing (round-then-sum, matching the durable-calculator
readout). A multi-year cadence contributes its fractional-year share (every third year -> a third a year).
"""
from dataclasses import dataclass
from decimal import Decimal

from django.template.loader import render_to_string

from ucfp.inputs.cadence import per_year

_TOTAL_TEMPLATE = 'inputs/interview/sections/_expense_total.html'


@dataclass( frozen = True )
class ExpenseTotal:
    """One total shown on a pane: the element id its value renders under (the single source both the
    template and the antinode `replace_map` key off, so the id is never hardcoded twice) and its
    whole-dollar yearly amount."""
    element_id : str
    amount     : Decimal


def annualized_sum( amount_cadence_pairs ) -> Decimal:
    """Sum `(amount, interval)` pairs as a whole-dollar yearly figure: each pair annualized via
    `per_year` (whole dollars, then summed), a missing amount counting as zero."""
    return sum( ( per_year( amount, interval ) for amount, interval in amount_cadence_pairs ),
                Decimal( 0 ) )


def rendered( request, totals : list ) -> dict:
    """Each total re-rendered as an id-keyed HTML fragment for an antinode `replace_map`, so a silent
    save refreshes the on-page totals without re-rendering (or disturbing) the edited pane."""
    fragments = dict()
    for total in totals:
        context = { 'id': total.element_id, 'amount': total.amount }
        fragments[ total.element_id ] = render_to_string( _TOTAL_TEMPLATE, context, request = request )
    return fragments


class ExpenseTotalsMatrix:
    """The totals for a spending pane whose amounts form a category-by-column matrix: a subtotal per
    (category, column) plus a page total per column. This shared shape is the same for the Living
    timeline (columns are age-span bands) and the Home matrix (columns are the Default and each
    property); only how a single column's amount is read differs. A form mixes this in and supplies the
    four primitives below; the pane's `sections` calls `attach_subtotals` to hang each section's
    subtotals on its header, and the view pushes `totals` back to the page after each edit."""

    _TOTALS_PREFIX : str = ''            # the id namespace for this pane's totals ('living', 'home')

    def _total_rows( self ) -> list:
        """The expense rows to total (each carries a `.category`)."""
        raise NotImplementedError

    def _total_columns( self ) -> int:
        """How many columns the matrix has (one figure is produced per column)."""
        raise NotImplementedError

    def _column_sum( self, rows, column : int ) -> Decimal:
        """The annual sum of `rows` down `column` -- the one pane-specific reading of an amount."""
        raise NotImplementedError

    @property
    def totals_row( self ) -> list:
        """The per-column page total (every row), one figure per column."""
        return [ ExpenseTotal( self._total_id( column ), self._column_sum( self._total_rows(), column ) )
                 for column in range( self._total_columns() ) ]

    @property
    def totals( self ) -> list:
        """Every subtotal and total the pane shows, flattened for the antinode push: each category's
        per-column subtotals, then the per-column page totals."""
        flat = list()
        for category in self._ordered_categories():
            flat.extend( self._subtotals_for( category ) )
        flat.extend( self.totals_row )
        return flat

    def attach_subtotals( self, sections : list ) -> list:
        """Hang each section's per-column subtotals on its dict (under `subtotals`), returning the same
        list -- so a pane's `sections` reads `section.subtotals` on the category header."""
        for section in sections:
            section[ 'subtotals' ] = self._subtotals_for( section[ 'category' ] )
        return sections

    def _subtotals_for( self, category ) -> list:
        rows = [ row for row in self._total_rows() if row.category is category ]
        return [ ExpenseTotal( self._subtotal_id( category, column ), self._column_sum( rows, column ) )
                 for column in range( self._total_columns() ) ]

    def _ordered_categories( self ) -> list:
        """The distinct categories in their shown (section) order."""
        categories = list()
        for row in self._total_rows():
            if row.category not in categories:
                categories.append( row.category )
        return categories

    def _subtotal_id( self, category, column : int ) -> str:
        return f'{self._TOTALS_PREFIX}-subtotal-{category.name.lower()}-{column}'

    def _total_id( self, column : int ) -> str:
        return f'{self._TOTALS_PREFIX}-total-{column}'
