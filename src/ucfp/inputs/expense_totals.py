"""Server-computed totals for the interview spending panes (#182).

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


def rendered( request, totals ) -> dict:
    """Each total re-rendered as an id-keyed HTML fragment for an antinode `replace_map`, so a silent
    save refreshes the on-page totals without re-rendering (or disturbing) the edited pane."""
    fragments = dict()
    for total in totals:
        context = { 'id': total.element_id, 'amount': total.amount }
        fragments[ total.element_id ] = render_to_string( _TOTAL_TEMPLATE, context, request = request )
    return fragments
