"""Wiring the general `accounts.books_table` layer to a captured run and the user's session lens.

The view layer's bridge: it turns a `ProjectionRunRecord` (plus the request's session lens) into a
rendered `BooksTable`. The general layer stays books-only; this is where a run's persisted books,
its period spans, and the per-user `SessionState` lens come together. The lens is adapted to each
run's books on read (adapt-on-read), leaving the stored lens untouched -- a column op (Phase 5)
is what rewrites it.
"""
from common.date_span import DateSpan

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.books_table import (
    BooksTable,
    BooksTableColumnCatalog,
    adapt,
    build_books_table,
)

from .schemas import ProjectionRun


def build_run_books_table( request, run : ProjectionRun, books : BooksOfAccount ) -> BooksTable:
    """The BooksTable to render for `run`: its books across the run's period spans, viewed through
    the user's session lens (or the default view) adapted to this books."""
    bookkeeper = Bookkeeper( books )
    spans      = [ DateSpan( step.start_date, step.end_date ) for step in run.result.steps ]
    catalog    = BooksTableColumnCatalog.build( bookkeeper.chart )
    stored     = request.session_state.books_table_definition
    base       = stored if stored is not None else catalog.default_definition()
    definition = adapt( base, catalog )
    return build_books_table( bookkeeper.ledger, bookkeeper.chart, spans, definition, catalog )
