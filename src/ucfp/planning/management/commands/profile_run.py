"""Profile the run-results display path, stage by stage, for one captured run.

The measurement floor for the forecast-display performance work: it re-executes exactly what
`RunResultsView` does to turn a stored run into the page -- deserialize the run, reload its books,
index the postings, build the column catalog, compute the books table, the outcome summary, the
balances sparkline, and (optionally) render the cell-heavy table fragment -- timing each stage and
counting the SQL it issues. Report `min`/`median` over several iterations so a change is measured,
not guessed, and the SQL count surfaces query-shape regressions (the N+1 in the books reload) that a
warm local wall-clock hides but a constrained deployment does not.

Two lenses are profiled: the `default` view a first-time viewer sees, and the `expanded` worst case
with every summary drilled open -- the widest table the cell computation and the template render ever
face. Read-only: it runs the display pipeline in-process against the dev database and writes nothing.
"""
import statistics
import time
import uuid
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext

from common.dataclass_json import from_json_data

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books_table import (
    BooksSummaryColumn, BooksTableColumnCatalog, build_books_table )
from ucfp.accounts.enums import CurrencyType
from ucfp.accounts.models import EntryRecord
from ucfp.accounts.repository import BooksOfAccountRepository

from ucfp.planning.books_table import run_period_spans
from ucfp.planning.materialization import primary_birthdate
from ucfp.planning.models import ProjectionRunRecord
from ucfp.planning.overview import run_outcome
from ucfp.planning.run_charts import CHROME_SPARKLINE, balances_chart
from ucfp.planning.schemas import ProjectionRun


# The cell-heavy fragment `RunResultsView` renders for the table -- rows x columns of formatted money,
# the render cost that scales with the lens width. Rendered here in isolation (no page shell) to time it.
_BOOKS_TABLE_TEMPLATE = 'planning/pages/run_books_table.html'

# The frontier can only deepen so far; this bounds the fully-expand loop against a pathological catalog.
_MAX_EXPANSION_ROUNDS = 30


@dataclass( frozen = True )
class _Sample:
    """One stage's cost in one pass: its wall time and the number of SQL queries it issued."""

    stage   : str
    millis  : float
    queries : int


class _Pass:
    """One timed walk through the display pipeline, accumulating a `_Sample` per stage. `measure`
    times a stage and captures the SQL it runs, returning the stage's result so the next stage can
    consume it -- the pipeline's data dependencies stay explicit in the caller."""

    def __init__( self ):
        self.samples : list[ _Sample ] = []

    def measure( self, stage : str, thunk ):
        # Clear the query log first so each stage's count starts from zero. Django caps the log at a
        # 9000-entry deque, so without this the books reload's thousands of queries would overflow it
        # and later stages would under-count (or read zero) against a full buffer.
        connection.queries_log.clear()
        with CaptureQueriesContext( connection ) as captured:
            start  = time.perf_counter()
            result = thunk()
            millis = ( time.perf_counter() - start ) * 1000
        self.samples.append( _Sample( stage, millis, len( captured ) ) )
        return result


class Command( BaseCommand ):
    help = ( 'Profile the run-results display path stage by stage for one captured run, reporting '
             'per-stage min/median wall time and SQL query counts over several iterations.' )

    def add_arguments( self, parser ):
        parser.add_argument(
            'run', nargs = '?',
            help = 'Run uuid to profile (default: the most recently captured run).' )
        parser.add_argument(
            '-n', '--iterations', type = int, default = 5,
            help = 'Timed iterations per lens after one warm-up (default: 5).' )
        parser.add_argument(
            '--lens', choices = ( 'default', 'expanded', 'both' ), default = 'both',
            help = 'Which column lens(es) to profile (default: both).' )
        parser.add_argument(
            '--no-render', action = 'store_true',
            help = 'Skip the table-fragment template render stage.' )

    def handle( self, *args, **options ):
        record = _resolve_record( options[ 'run' ] )
        render = not options[ 'no_render' ]
        self._report_shape( record )
        lenses = ( 'default', 'expanded' ) if options[ 'lens' ] == 'both' else ( options[ 'lens' ], )
        for lens in lenses:
            self._profile_lens( record, lens = lens, iterations = options[ 'iterations' ],
                                render = render )
        return

    def _profile_lens( self, record, *, lens : str, iterations : int, render : bool ):
        expand = ( lens == 'expanded' )
        _profile_pass( record, expand = expand, render = render )   # warm-up, discarded
        passes = [ _profile_pass( record, expand = expand, render = render ).samples
                   for _ in range( iterations ) ]
        self._report_lens( lens, passes )
        return

    def _report_shape( self, record ):
        entries = EntryRecord.objects.filter( transaction__books = record.books ).count()
        self.stdout.write( self.style.MIGRATE_HEADING(
            f"Run '{record.label}' ({record.uuid})" ) )
        self.stdout.write(
            f'  accounts {record.books.accounts.count()}  '
            f'transactions {record.books.transactions.count()}  '
            f'entries {entries}' )
        return

    def _report_lens( self, lens : str, passes : list[ list[ _Sample ] ] ):
        self.stdout.write( f'\n{lens} lens  ({len( passes )} iterations)' )
        self.stdout.write( f'  {"stage":22s} {"min ms":>9s} {"median ms":>10s} {"queries":>8s}' )
        total_min = total_median = total_queries = 0.0
        for stage_samples in zip( *passes ):
            millis  = sorted( sample.millis for sample in stage_samples )
            queries = stage_samples[ 0 ].queries   # deterministic across iterations
            total_min      += millis[ 0 ]
            total_median   += statistics.median( millis )
            total_queries  += queries
            self.stdout.write(
                f'  {stage_samples[ 0 ].stage:22s} {millis[ 0 ]:9.1f} '
                f'{statistics.median( millis ):10.1f} {queries:8d}' )
            continue
        self.stdout.write(
            f'  {"TOTAL":22s} {total_min:9.1f} {total_median:10.1f} {int( total_queries ):8d}' )
        return


def _profile_pass( record : ProjectionRunRecord, *, expand : bool, render : bool ) -> _Pass:
    """One instrumented pass of the display pipeline, mirroring `RunResultsView.get`. Each stage is
    the same call the view makes; the lens is the default view or -- when `expand` -- the fully
    drilled-open worst case."""
    walk       = _Pass()
    run        = walk.measure( 'deserialize run', lambda : from_json_data( ProjectionRun, record.data ) )
    books      = walk.measure( 'load books', lambda : BooksOfAccountRepository().load( record.books ) )
    bookkeeper = walk.measure( 'index postings', lambda : Bookkeeper( books ) )
    catalog    = walk.measure( 'build catalog',
                               lambda : BooksTableColumnCatalog.build( bookkeeper.chart ) )
    spans      = run_period_spans( run )
    definition = _lens( catalog, expand = expand )
    table      = walk.measure(
        'build table',
        lambda : build_books_table( bookkeeper.ledger, bookkeeper.chart, spans, definition, catalog ) )
    walk.measure( 'run_outcome', lambda : run_outcome( run, books ) )
    walk.measure( 'balances sparkline', lambda : balances_chart( run, books, chrome = CHROME_SPARKLINE ) )
    if render:
        context = _render_context( record, run, table )
        walk.measure( 'render table html',
                      lambda : render_to_string( _BOOKS_TABLE_TEMPLATE, context ) )
    return walk


def _lens( catalog : BooksTableColumnCatalog, *, expand : bool ):
    """The lens to profile: the default view, or -- when `expand` -- every summary drilled open."""
    definition = catalog.default_definition().adapt( catalog )
    return _fully_expanded( catalog, definition ) if expand else definition


def _fully_expanded( catalog : BooksTableColumnCatalog, definition ):
    """`definition` with every summary on the frontier expanded, repeated until the frontier stops
    growing -- the widest table the lens can show, the worst case for the cell computation and render."""
    for _round in range( _MAX_EXPANSION_ROUNDS ):
        widened = definition
        for key in definition.column_keys:
            if isinstance( catalog.get( key ), BooksSummaryColumn ):
                widened = widened.expand( catalog, key )
            continue
        if widened.column_keys == definition.column_keys:
            return definition
        definition = widened
        continue
    return definition


def _render_context( record : ProjectionRunRecord, run : ProjectionRun, table ) -> dict:
    """The context the table fragment reads (`planning/pages/run_books_table.html`): the built table,
    the run record (for column-op URLs), the sticky Age column inputs, and the display currency the
    `money` filter needs. Age mirrors `books_table._age_column_context`; currency mirrors the
    `current_currency` context processor, falling back to the default when the org has none."""
    currency = getattr( record.organization, 'currency', None ) or CurrencyType.default()
    return {
        'books_table'   : table,
        'record'        : record,
        'age_birthdate' : primary_birthdate( run.profile ),
        'show_age'      : run.frame.granularity.months() == 12,
        'currency'      : currency,
        # A placeholder so `{% csrf_token %}` in the fragment's forms renders (and stays part of the
        # measured work) without a real request -- there is no live request in this in-process pass.
        'csrf_token'    : 'profiling',
    }


def _resolve_record( identifier : str ) -> ProjectionRunRecord:
    """The run to profile: the record for `identifier`, or the most recently captured run when omitted."""
    if identifier is None:
        record = ProjectionRunRecord.objects.order_by( '-id' ).first()
        if record is None:
            raise CommandError( 'No captured runs in the database; capture one first.' )
        return record
    try:
        run_uuid = uuid.UUID( identifier )
    except ValueError:
        raise CommandError( f'{identifier!r} is not a valid run uuid.' )
    record = ProjectionRunRecord.objects.filter( uuid = run_uuid ).first()
    if record is None:
        raise CommandError( f'No captured run with uuid {identifier}.' )
    return record
