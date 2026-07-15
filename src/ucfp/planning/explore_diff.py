"""Structural diff of two scenarios' curated inputs -- what the Explore dials changed.

Compares the dial-editable fields (the curated discretionary expenses, per age band, and the headline
economic rates) between two `Scenario`s and yields short human descriptions. This drives the run-strip
labels (what changed between successive runs) and the save affordance (how far the working scenario has
drifted from where the exploration started). A fuller field-level diff over all inputs is a later phase.
"""
from ucfp.inputs.scenarios.schemas import Scenario

from .explore_sections import _CURATED_EXPENSES, _CURATED_RATES, _band_labels


def curated_changes( before: Scenario, after: Scenario ) -> list:
    """Short descriptions of the curated fields that differ from `before` to `after`."""
    band_labels = _band_labels( after.plans.expense_spans or [ None ] )
    return ( _rate_changes( before.assumptions.economics, after.assumptions.economics )
             + _expense_changes(
                 before.plans.recurring_expenses, after.plans.recurring_expenses, band_labels ) )


def describe_changes( changes: list ) -> str:
    """A compact label for a set of changes -- the change itself when there is exactly one, else a count."""
    if not changes:
        return 'no change'
    return changes[ 0 ] if len( changes ) == 1 else f'{len( changes )} changes'


def _rate_changes( before, after ) -> list:
    if ( before is None ) or ( after is None ):
        return list()
    changes = list()
    for attr, label in _CURATED_RATES:
        earlier, later = getattr( before, attr ).fraction, getattr( after, attr ).fraction
        if earlier != later:
            changes.append( f'{label} {_pct( earlier )}→{_pct( later )}%' )
    return changes


def _expense_changes( before, after, band_labels ) -> list:
    by_before = { expense.handle: expense for expense in before }
    by_after  = { expense.handle: expense for expense in after }
    changes   = list()
    for handle, label in _CURATED_EXPENSES:
        earlier, later = by_before.get( handle ), by_after.get( handle )
        if ( earlier is None ) or ( later is None ):
            continue
        for band, ( was, now ) in enumerate( zip( earlier.amounts, later.amounts ) ):
            if was != now:                                     # one entry per differing band, band-labelled
                changes.append( f'{label}{_band_suffix( band, band_labels )} {_num( was )}→{_num( now )}' )
    return changes


def _band_suffix( band: int, band_labels ) -> str:
    """The age-range qualifier for a changed band, e.g. ` (65–75)` -- omitted for a single all-ages band,
    where naming the band adds no information."""
    if len( band_labels ) <= 1 or band >= len( band_labels ):
        return ''
    return f' ({band_labels[ band ]})'


def _pct( fraction ) -> str:
    return f'{fraction * 100:g}'


def _num( value ) -> str:
    return f'{value:g}'
