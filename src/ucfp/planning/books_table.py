"""Wiring the general `accounts.books_table` layer to a captured run and the user's session lens.

The view layer's bridge: it turns a run's persisted books (plus the request's session lens) into
the context for the #books-table fragment, and applies a column operation to the lens -- persisting
it (persist-on-op) and re-rendering. The column logic itself lives on `BooksTableDefinition`; this
is the run / session / HTTP glue. The lens is adapted to each run's books on read, leaving the
stored lens untouched until an operation rewrites it.
"""
from typing import Optional

from django.core.exceptions import BadRequest

from common.date_span import DateSpan

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.books_table import (
    BooksColumnKey,
    BooksTableColumnCatalog,
    BooksTableDefinition,
    build_books_table,
)

from .schemas import ProjectionRun


def run_books_table_context( request, run : ProjectionRun, books : BooksOfAccount ) -> dict:
    """Template context for the #books-table fragment: the table seen through the user's lens
    (adapted to this run's books), plus the columns still available to add."""
    bookkeeper = Bookkeeper( books )
    catalog    = BooksTableColumnCatalog.build( bookkeeper.chart )
    definition = _current_definition( request, catalog )
    return _fragment_context( bookkeeper, catalog, run, definition )


def apply_run_books_operation( request, run : ProjectionRun, books : BooksOfAccount,
                               operation : Optional[ str ],
                               token : Optional[ str ] ) -> dict:
    """Apply a column operation to the user's lens, persist the result, and return the fragment
    context for the updated table."""
    bookkeeper = Bookkeeper( books )
    catalog    = BooksTableColumnCatalog.build( bookkeeper.chart )
    definition = _operate( _current_definition( request, catalog ), catalog, operation, token )
    request.session_state.books_table_definition = definition
    request.session_state.to_session( request )
    return _fragment_context( bookkeeper, catalog, run, definition )


def _current_definition( request,
                         catalog : BooksTableColumnCatalog ) -> BooksTableDefinition:
    """The user's stored lens (or the default view) adapted to this books -- adapt-on-read, which
    leaves the stored lens untouched."""
    stored = request.session_state.books_table_definition
    base   = stored if stored is not None else catalog.default_definition()
    return base.adapt( catalog )


def _fragment_context( bookkeeper : Bookkeeper, catalog : BooksTableColumnCatalog,
                       run : ProjectionRun, definition : BooksTableDefinition ) -> dict:
    period_spans = [ DateSpan( step.start_date, step.end_date ) for step in run.result.steps ]
    spans        = _spans_with_opening( period_spans )
    return {
        'books_table' : build_books_table(
            bookkeeper.ledger, bookkeeper.chart, spans, definition, catalog ),
    }


def _spans_with_opening( period_spans : list ) -> list:
    """`period_spans` led by an opening row -- a zero-length span at the day before the first period,
    the date the ledger reads opening balances through (the prior period's close). Its balance columns
    then show the starting position, and its flow columns are zero (no period precedes it), so the table
    opens with where the household stands before the first period rather than only at its close."""
    if not period_spans:
        return period_spans
    opening = period_spans[ 0 ].day_before_start
    return [ DateSpan( opening, opening ) ] + period_spans


def _operate( definition : BooksTableDefinition, catalog : BooksTableColumnCatalog,
              operation : Optional[ str ], token : Optional[ str ] ) -> BooksTableDefinition:
    """Dispatch a request's operation name to the matching definition method."""
    key = BooksColumnKey( token ) if token else None
    if operation == 'expand':
        return definition.expand( catalog, key )
    if operation == 'collapse':
        return definition.collapse( catalog, key )
    if operation == 'remove':
        return definition.remove( key )
    if operation == 'restore':
        return definition.restore( key )
    if operation == 'move_left':
        return definition.move( key, -1 )
    if operation == 'move_right':
        return definition.move( key, 1 )
    raise BadRequest( f'Unknown books-table operation: {operation!r}' )
