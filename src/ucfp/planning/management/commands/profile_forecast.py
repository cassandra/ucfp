"""Profile the forecast *run* path (compute + capture), isolated from result display.

The run action a user triggers is `run_and_capture`: materialize the inputs into engine parameters,
run the pure `Forecast` engine, stamp display placements, then persist the books and record the run.
On the deployed host the run and the subsequent results display blur together; this separates them and
breaks the run itself into its phases, timing each and counting the SQL it issues, so a glaring
inefficiency (a slow phase, an unexpected query in the compute loop, a heavy persist) stands out.

It reproduces a real run from a captured run's stored inputs (`record.data` carries the Profile, Plans,
Assumptions, and frame that produced it), so the shape matches production without reconstructing inputs.
The pure engine run is also cProfiled to surface its hottest functions. The persist phase runs inside a
rolled-back transaction, so profiling writes nothing. Read-only overall.
"""
import cProfile
import io
import pstats
import statistics
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from common.dataclass_json import from_json_data
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.forecast.forecast import Forecast

from ucfp.planning.display_placement import stamp_display_placements
from ucfp.planning.materialization import ForecastFrame, materialize
from ucfp.planning.models import ProjectionRunRecord
from ucfp.planning.schemas import ProjectionRun


_GRANULARITIES = {
    'year'    : Duration( 1, TimeUnit.YEAR ),
    'quarter' : Duration( 3, TimeUnit.MONTH ),
    'month'   : Duration( 1, TimeUnit.MONTH ),
}


class _Rollback( Exception ):
    """Unwinds the persist phase's transaction so profiling leaves no rows behind."""


class Command( BaseCommand ):
    help = ( 'Profile the forecast run path (materialize / engine run / stamp / persist) for a captured '
             "run's inputs, with per-phase timing, SQL counts, and a cProfile of the pure engine." )

    def add_arguments( self, parser ):
        parser.add_argument(
            'run', nargs = '?',
            help = 'Run uuid whose stored inputs to replay (default: the most recent run).' )
        parser.add_argument(
            '-n', '--iterations', type = int, default = 3,
            help = 'Timed iterations for the pure phases (materialize, run) after a warm-up (default: 3).' )
        parser.add_argument(
            '--granularity', choices = sorted( _GRANULARITIES ),
            help = 'Override the run granularity to see how the engine scales with period count '
                   '(default: the run\'s own).' )
        parser.add_argument(
            '--top', type = int, default = 25,
            help = 'How many hot functions to show from the engine cProfile (default: 25).' )

    def handle( self, *args, **options ):
        record = _resolve_record( options[ 'run' ] )
        run    = from_json_data( ProjectionRun, record.data )
        frame  = _frame( run.frame, options[ 'granularity' ] )
        self._report_shape( record, run, frame )
        self._report_phases( record, run, frame, iterations = options[ 'iterations' ] )
        self._report_engine_hotspots( run, frame, top = options[ 'top' ] )
        return

    def _report_shape( self, record, run, frame ):
        parameters = materialize( profile = run.profile, plans = run.plans,
                                  assumptions = run.assumptions, frame = frame )
        spans = parameters.period_spans()
        self.stdout.write( self.style.MIGRATE_HEADING(
            f"Run '{record.label}' ({record.uuid})" ) )
        self.stdout.write(
            f'  granularity {frame.granularity.count} {frame.granularity.unit.name.lower()}  '
            f'periods {len( spans )}  '
            f'horizon {frame.start_date} -> {frame.end_date}  '
            f'subjects {len( run.profile.subjects )}  assets {len( run.profile.assets )}' )
        return

    def _report_phases( self, record, run, frame, *, iterations : int ):
        def materialize_call():
            return materialize( profile = run.profile, plans = run.plans,
                                assumptions = run.assumptions, frame = frame )
        parameters = materialize_call()

        run_samples, materialize_samples = [], []
        _measure( lambda : Forecast( materialize_call() ).run() )   # warm-up (discarded)
        for _ in range( iterations ):
            _, materialize_ms, materialize_q = _measure( materialize_call )
            _, run_ms, run_q = _measure( lambda : Forecast( parameters ).run() )
            materialize_samples.append( ( materialize_ms, materialize_q ) )
            run_samples.append( ( run_ms, run_q ) )
            continue

        result = Forecast( parameters ).run()
        _, stamp_ms, stamp_q = _measure(
            lambda : stamp_display_placements( result.books, run.profile ) )
        save_ms, save_q = _persist_cost( result, record.organization )

        self.stdout.write( f'\n  {"phase":16s} {"min ms":>9s} {"median ms":>10s} {"queries":>8s}' )
        self._phase_row( 'materialize', materialize_samples )
        self._phase_row( 'run engine', run_samples )
        self.stdout.write( f'  {"stamp placements":16s} {stamp_ms:9.1f} {stamp_ms:10.1f} {"0":>8s}' )
        self.stdout.write( f'  {"persist books":16s} {save_ms:9.1f} {save_ms:10.1f} {save_q:8d}'
                           '   (rolled back)' )
        return

    def _phase_row( self, label, samples ):
        millis  = sorted( ms for ms, _ in samples )
        queries = samples[ 0 ][ 1 ]
        self.stdout.write(
            f'  {label:16s} {millis[ 0 ]:9.1f} {statistics.median( millis ):10.1f} {queries:8d}' )
        return

    def _report_engine_hotspots( self, run, frame, *, top : int ):
        parameters = materialize( profile = run.profile, plans = run.plans,
                                  assumptions = run.assumptions, frame = frame )
        profiler = cProfile.Profile()
        profiler.enable()
        Forecast( parameters ).run()
        profiler.disable()
        for sort_key, title in ( ( 'tottime', 'own time (tottime)' ),
                                 ( 'cumulative', 'cumulative time' ) ):
            buffer = io.StringIO()
            stats  = pstats.Stats( profiler, stream = buffer ).strip_dirs().sort_stats( sort_key )
            stats.print_stats( top )
            self.stdout.write( f'\nEngine hotspots by {title}:' )
            self.stdout.write( _trim_pstats( buffer.getvalue(), top ) )
            continue
        return


def _measure( thunk ):
    """Run `thunk`, returning `(result, elapsed_ms, query_count)`. The query log is cleared first so each
    measurement's count is independent and never overflows Django's capped log."""
    connection.queries_log.clear()
    with CaptureQueriesContext( connection ) as captured:
        start  = time.perf_counter()
        result = thunk()
        millis = ( time.perf_counter() - start ) * 1000
    return result, millis, len( captured )


def _persist_cost( result, organization ) -> tuple:
    """The `(elapsed_ms, query_count)` to persist the run's books -- inside a transaction that is rolled
    back, so profiling writes nothing."""
    try:
        with transaction.atomic():
            _, millis, queries = _measure(
                lambda : BooksOfAccountRepository().save( result.books, organization ) )
            raise _Rollback()
    except _Rollback:
        pass
    return millis, queries


def _trim_pstats( text : str, top : int ) -> str:
    """The pstats table trimmed to its header and the top rows -- pstats prints a caller preamble and all
    rows; keep the column header and the `top` function lines."""
    lines = [ line for line in text.splitlines() if line.strip() ]
    header = next( ( index for index, line in enumerate( lines )
                     if 'ncalls' in line and 'tottime' in line ), 0 )
    return '\n'.join( lines[ header : header + top + 1 ] )


def _frame( frame, granularity : str ) -> ForecastFrame:
    """The run's frame, optionally with a different granularity to probe how the engine scales with the
    number of periods."""
    if granularity is None:
        return frame
    return ForecastFrame( start_date = frame.start_date, end_date = frame.end_date,
                          granularity = _GRANULARITIES[ granularity ] )


def _resolve_record( identifier : str ) -> ProjectionRunRecord:
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
