"""The forecast overview: a compact, display-ready summary of an organization's financial-forecast
state, for surfaces that show the forecast without being the hub -- today the dashboard card.

Two layers live here. `run_outcome` is the per-run headline (the salient result plus the start->end arc),
shared by every page that shows a single captured run (the results page, and the dashboard card). Built on
it, `forecast_overview` decides which of four states the dashboard's forecast card is in -- a saved run to
recap, ready to run but no runs yet, or a missing prerequisite (no profile, or no runnable scenario) -- so
the view stays a thin caller and the card a thin renderer. The setup states carry exactly what the hub's
own `scenario_required` pane needs, so the card reuses it rather than restating the gating.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from common.dataclass_json import from_json_data
from common.datetime_utils import age_on
from common.line_chart import CHROME_FULL

from organization.models import Organization

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.state import completed_profile

from .enums import PlanningFeature
from .gating import partition_scenarios, scenario_started
from .run_books_cache import load_run_books
from .models import PlanningResultRecord
from .books_table import run_period_spans
from .inflation import to_todays_dollars
from .run_charts import net_worth_chart as build_net_worth_chart
from .schemas import ProjectionRun


def run_outcome( run : ProjectionRun, books ) -> dict:
    """The run's headline outcome, shared by every page that shows a run: the salient result and the
    start->end arc (year, household ages, net worth). A run that stopped early ends at its last computed
    period, not the horizon; net worth is computed live from the already-loaded books -- never cached --
    keeping the books the one source of truth (a captured run is immutable, so the live figure is stable)."""
    frame  = run.frame
    ledger = Bookkeeper( books ).snapshot_ledger
    steps  = run.result.steps
    # The starting net worth is read at the opening instant -- the day before the first period, the same
    # point the books table's opening row and the chart's first point use (`run_period_spans`' opening span).
    # Reading it at `frame.start_date` instead would include the first period's growth, which the engine
    # books at the period's start date, overstating the "starting" figure against the table and chart.
    opening_span = run_period_spans( run )[ 0 ]
    opening_date = opening_span.end_date
    lasted = not run.result.stopped_early
    end_date = frame.end_date if lasted else steps[ -1 ].end_date
    depleted = ( not lasted ) and steps[ -1 ].is_depleted
    end_net_worth = ledger.net_worth( through = end_date )
    solvent = end_net_worth >= 0
    start_ages = _ages( run.profile, frame.start_date )
    end_ages   = _ages( run.profile, end_date )
    return {
        'summary' : {
            'lasted'   : lasted,
            'depleted' : depleted,
            # Years the plan ran: the full horizon when it lasted, else through the period it stopped in.
            'years'    : end_date.year - frame.start_date.year + 1,
            # The heading for the ages column -- singular for one member, plural for a couple.
            'age_noun' : _age_noun( start_ages ),
            'start'    : {
                'year'      : frame.start_date.year,
                'ages'      : _join_ages( start_ages ),
                'net_worth' : ledger.net_worth( through = opening_date ) },
            'end'      : {
                'year'            : end_date.year,
                'ages'            : _join_ages( end_ages ),
                # Ending net worth is shown only when solvent; a depleted plan's is noise the result covers.
                'net_worth'       : end_net_worth,
                'has_net_worth'   : solvent,
                # The nominal ending net worth restated in start-year ("today's") dollars, so a far-horizon
                # figure is read against money the viewer knows. None when the restatement would add nothing
                # -- not solvent, a same-year horizon, or a zero/absent inflation assumption -- and the
                # summary then simply omits the companion line.
                'net_worth_today' : to_todays_dollars( run, end_net_worth, end_date ) if solvent else None } } }


def _ages( profile, on_date ) -> list:
    """The household's whole-year ages on `on_date`, one per subject (empty when there are none). True age
    from the birthdate, so a December birthday still reads a year younger through a run that starts earlier
    in the year. The summary shows these bare (as a column) with the noun carried by `_age_noun`."""
    return [ age_on( subject.birthdate, on_date ) for subject in profile.subjects ]


def _age_noun( ages ) -> str:
    """The ages column's heading -- 'Age' for one member, 'Ages' for a couple, '' for none."""
    if not ages:
        return ''
    return 'Age' if len( ages ) == 1 else 'Ages'


def _age_span_label( profile, start_date, end_date ) -> str:
    """The household's age progression across the run -- 'age 66 → 90' for one member, 'ages 65 & 63 → 89 &
    87' for a couple, '' for none. Pairs with the year span in the dashboard's Horizon figure, so both
    endpoints read at the same two dates the years do (the planned frame)."""
    starts = [ age_on( subject.birthdate, start_date ) for subject in profile.subjects ]
    ends   = [ age_on( subject.birthdate, end_date ) for subject in profile.subjects ]
    if not starts:
        return ''
    prefix = 'age' if len( starts ) == 1 else 'ages'
    return f'{prefix} {_join_ages( starts )} → {_join_ages( ends )}'


def _join_ages( ages ) -> str:
    """Ages as 'a' or 'a & b' -- the household's members joined for a label."""
    return ' & '.join( str( age ) for age in ages )


class ForecastState( Enum ):
    """Which card the dashboard's forecast overview shows. Ordered from the richest (a run to recap) down
    through the setup ladder the hub already gates on -- so the dashboard routes to the precise next step
    rather than a generic 'set things up' prompt."""
    HAS_RUN        = 'has_run'          # a saved run to recap
    READY_NO_RUNS  = 'ready_no_runs'    # runnable, but nothing saved yet
    NEEDS_PROFILE  = 'needs_profile'    # no complete profile -- the first prerequisite
    NEEDS_SCENARIO = 'needs_scenario'   # a complete profile, but no runnable scenario


@dataclass( frozen = True )
class ForecastRunCard:
    """The display facts the dashboard's forecast card shows for the latest saved run: its identity (for the
    'View run' link and the recap line) and the three headline figures -- horizon, ending net worth, and
    outcome. Horizon is the planned frame (always available from the parsed run); the net-worth and outcome
    figures come from `run_outcome`. `end_net_worth` is None for a plan that did not stay solvent, in which
    case the card reads 'Depleted' rather than a number (mirroring the run results summary)."""
    run_uuid         : object
    label            : str
    source_label     : Optional[ str ]
    created_datetime : object
    start_year       : int
    end_year         : int
    duration_years   : int
    age_span         : str
    lasted           : bool
    depleted         : bool
    ran_out_year     : Optional[ int ]
    start_net_worth  : Decimal
    end_net_worth    : Optional[ Decimal ]
    net_worth_chart  : object            # a LineChart of net worth over the run (full chrome)

    @property
    def has_end_net_worth( self ) -> bool:
        return self.end_net_worth is not None


@dataclass( frozen = True )
class ForecastOverview:
    """The dashboard forecast card's whole view-model: its `state` plus whatever that state renders. HAS_RUN
    carries the `card`; NEEDS_SCENARIO carries the in-progress scenario to build or resume (the same two
    fields the shared `scenario_required` pane reads). The `is_*` properties keep the template's branching
    readable."""
    state                  : ForecastState
    card                   : Optional[ ForecastRunCard ] = None
    build_scenario         : object                      = None
    build_scenario_started : bool                        = False

    @property
    def has_run( self ) -> bool:
        return self.state is ForecastState.HAS_RUN

    @property
    def ready_no_runs( self ) -> bool:
        return self.state is ForecastState.READY_NO_RUNS

    @property
    def needs_profile( self ) -> bool:
        return self.state is ForecastState.NEEDS_PROFILE

    @property
    def needs_scenario( self ) -> bool:
        return self.state is ForecastState.NEEDS_SCENARIO


def forecast_overview( organization : Organization, *,
                       adjust_for_inflation : bool = False ) -> ForecastOverview:
    """The forecast card's state for `organization`. A saved run always wins (it is immutable and always
    viewable, whatever the inputs look like now), so it is checked first; only then does the setup ladder
    apply -- a complete profile, then a runnable scenario. The ladder mirrors the hub's own gating, and the
    NEEDS_SCENARIO result carries the scenario the shared pane will offer to build or resume.
    `adjust_for_inflation` draws the card's net-worth chart in today's dollars (the session preference)."""
    latest = _latest_saved_run( organization )
    if latest is not None:
        return ForecastOverview(
            state = ForecastState.HAS_RUN, card = _run_card( latest, adjust_for_inflation ) )

    profile_record = completed_profile( organization )
    if profile_record is None:
        return ForecastOverview( state = ForecastState.NEEDS_PROFILE )

    complete, _drift_blocked, in_progress = partition_scenarios( organization, profile_record )
    if complete:
        return ForecastOverview( state = ForecastState.READY_NO_RUNS )

    started = next( ( scenario for scenario in in_progress if scenario_started( scenario ) ), None )
    return ForecastOverview(
        state                  = ForecastState.NEEDS_SCENARIO,
        build_scenario         = started or ( in_progress[ 0 ] if in_progress else None ),
        build_scenario_started = started is not None )


def _latest_saved_run( organization : Organization ) -> Optional[ PlanningResultRecord ]:
    """The organization's most recent saved financial-forecast result, or None -- the run the dashboard
    recaps. Same filter the hub's list uses (saved forecast results), newest first."""
    return ( PlanningResultRecord.objects.select_related( 'run' )
             .filter( organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                      usage_role = UsageRole.SAVED )
             .order_by( '-created_datetime' ).first() )


def _run_card( result : PlanningResultRecord, adjust_for_inflation : bool = False ) -> ForecastRunCard:
    """The display card for a saved run: its identity plus the horizon and the net-worth/outcome figures,
    the latter from a single books load through `run_outcome` (one run's books -- the dashboard's only
    projection load). Horizon comes from the parsed frame, so it is right even if the run stopped early."""
    run     = from_json_data( ProjectionRun, result.run.data )
    books   = load_run_books( result.run.books )
    summary = run_outcome( run, books )[ 'summary' ]
    frame   = run.frame
    end     = summary[ 'end' ]
    return ForecastRunCard(
        run_uuid         = result.run.uuid,
        label            = result.run.label,
        source_label     = result.run.source_label,
        created_datetime = result.created_datetime,
        start_year       = frame.start_date.year,
        end_year         = frame.end_date.year,
        duration_years   = frame.end_date.year - frame.start_date.year + 1,
        age_span         = _age_span_label( run.profile, frame.start_date, frame.end_date ),
        lasted           = summary[ 'lasted' ],
        depleted         = summary[ 'depleted' ],
        # The year the plan ran dry -- only when depleted; the outcome line reads 'Ran out in <year>'.
        ran_out_year     = end[ 'year' ] if summary[ 'depleted' ] else None,
        start_net_worth  = summary[ 'start' ][ 'net_worth' ],
        end_net_worth    = end[ 'net_worth' ] if end[ 'has_net_worth' ] else None,
        net_worth_chart  = build_net_worth_chart(
            run, books, chrome = CHROME_FULL, adjust_for_inflation = adjust_for_inflation,
            width = 960, height = 220 ) )
