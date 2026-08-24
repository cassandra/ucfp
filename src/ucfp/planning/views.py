"""The Financial Forecast hub and per-run results.

The hub (`/plan/financial-forecast/`) orchestrates the flow without re-implementing the profile or
plans forms: it links out to them, makes the forecast bundle explicit (which profile, which plans,
which assumptions, the frame), runs it, and lists past runs. The results page (`/run/<uuid>/`) shows
a captured run -- the net-worth trajectory derived from its persisted books, whether it stopped
early, and the notices. The interview and the input editors live in the `inputs` app.
"""

from datetime import date

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from organization.decorators import PermitsReadonlyMutation, ensure_organization

from common import antinode
from common.async_view import ModalView
from common.dataclass_json import from_json_data
from common.line_chart import CHROME_FULL, CHROME_SPARKLINE

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books_table import BooksColumnKey
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.inputs.drift import plans_drift
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.mixins import InputGatedMixin
from ucfp.inputs.models import ScenarioRecord
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.state import completed_profile
from ucfp.inputs.scenarios.exploration import (
    OVERWRITE, branch_destinations, component_usage, overwrite_working, record_exploration_frame,
    save_working, scenario_exploration, working_scenario )
from ucfp.inputs.scenarios.repository import load_scenario, scenarios_for

from .books_table import apply_run_books_operation, run_books_table_context
from .enums import PlanningFeature
from .explore import delete_runs, run_working_scenario, start_fresh_exploration, transient_runs
from .explore_diff import describe_changes, value_changes
from .profile_diff import profile_changes
from .explore_sections import EconomicAssumptionsExploreForm, LivingExpensesExploreForm
from .forms import ForecastForm
from .frames import FORECAST_MIN_YEARS, GRANULARITY, default_forecast_duration_years, resolve_frame
from .gating import partition_scenarios, scenario_readiness, scenario_started
from .materialization import ForecastFrame
from .models import ProjectionRunRecord, PlanningResultRecord
from .orchestration import run_and_capture, run_title
from .overview import run_outcome
from .run_charts import balances_chart, column_chart, flows_chart
from .schemas import ProjectionRun

_HUB_TEMPLATE = 'planning/pages/financial_forecast.html'
_RESULTS_TEMPLATE = 'planning/pages/run_results.html'
_BOOKS_TABLE_TEMPLATE = 'planning/pages/run_books_table.html'
_JOURNAL_TEMPLATE = 'planning/modals/account_journal.html'
_DISCARD_CONFIRM_TEMPLATE = 'planning/modals/run_discard_confirm.html'
_CHARTS_MODAL_TEMPLATE = 'planning/modals/run_charts.html'
_COLUMN_CHART_MODAL_TEMPLATE = 'planning/modals/run_column_chart.html'
_EXPLORE_SAVE_TEMPLATE = 'planning/modals/explore_save.html'
_COMING_SOON_TEMPLATE = 'planning/pages/coming_soon.html'

# The unbuilt planning features: title + one-line pitch for their placeholder pages.
_COMING_SOON = {
    'retirement_timing'  : ( 'Retirement Timing',
                             'When can I retire? Sweep retirement dates to find the earliest feasible one.' ),
    'social_security'    : ( 'Social Security',
                             'When should I claim? Compare claiming strategies side by side.' ),
    'cash_flow_planning' : ( 'Cash Flow',
                             'Will I have enough? A fine-grained look at the next ~12 months.' ),
}


@method_decorator( ensure_organization, name = 'dispatch' )
class ComingSoonView( TemplateView ):
    """A first-class but unbuilt planning feature: real route and nav presence, placeholder body.
    `feature_key` selects the title/pitch from `_COMING_SOON` (set per route via `as_view`)."""

    template_name = _COMING_SOON_TEMPLATE
    feature_key   = None

    def get_context_data( self, **kwargs ):
        context = super().get_context_data( **kwargs )
        title, pitch = _COMING_SOON[ self.feature_key ]
        context.update( feature_title = title, feature_pitch = pitch )
        return context


def _run_frame( result ) -> ForecastFrame:
    """The frame a captured transient run was projected over, read from its embedded snapshot -- so the
    workspace can tell whether an existing run still matches the exploration's current frame."""
    return from_json_data( ProjectionRun, result.run.data ).frame


def _saved_run_digest( run_record ):
    """Cheap, cache-free display facts for a saved-run row, read straight from the captured run JSON (no
    books load): the projection's year span and whether the money lasted (or the year it ran out). All of
    this already lives in the immutable run, so nothing is cached or can drift. Returns None if the data is
    absent or malformed -- the row then falls back to just its name and date, so a run captured under an
    older (or later) shape never breaks the list."""
    try:
        data   = run_record.data
        frame  = data[ 'frame' ]
        result = data[ 'result' ]
        start_year = date.fromisoformat( frame[ 'start_date' ] ).year
        end_year   = date.fromisoformat( frame[ 'end_date' ] ).year
        ran_out_year = None
        if result.get( 'stopped_early' ):
            depleted = next( ( step for step in result[ 'steps' ] if step.get( 'is_depleted' ) ), None )
            ran_out_year = date.fromisoformat( depleted[ 'end_date' ] ).year if depleted else None
        return {
            'start_year'     : start_year,
            'end_year'       : end_year,
            'duration_years' : end_year - start_year + 1,
            'lasted'         : not result.get( 'stopped_early' ),
            'ran_out_year'   : ran_out_year,
            # How far before the planned horizon the money ran out -- distinguishes a near miss from an
            # early collapse. None when the money lasts or the depletion year is unknown.
            'years_short'    : ( end_year - ran_out_year ) if ran_out_year else None,
        }
    except ( KeyError, TypeError, ValueError ):
        return None


def _default_duration_years( profile_record ) -> int:
    """The hub's first-time duration default: the age-based horizon for the current profile, or the bare
    floor when there is no complete profile (nothing is runnable then, so the value is only cosmetic)."""
    if profile_record is None:
        return FORECAST_MIN_YEARS
    return default_forecast_duration_years( load_profile( profile_record ), profile_record.effective_date )


def _remember_selection( request, form, scenario_record ) -> None:
    """Persist the chosen scenario and frame to the session, so the hub chooser defaults to them on the
    next visit and Explore (which reads the frame from the session) projects over the same window."""
    request.session_state.current_scenario_uuid   = str( scenario_record.uuid )
    request.session_state.forecast_start_from     = form.cleaned_data[ 'start_from' ]
    request.session_state.forecast_duration_years = form.cleaned_data[ 'duration_years' ]
    request.session_state.forecast_interval       = form.cleaned_data[ 'interval' ]
    request.session_state.to_session( request )


class FinancialForecastView( InputGatedMixin, View ):
    """`/plan/financial-forecast/` -- the hub: pick a complete scenario and a frame, then either run it
    (this view's POST) or open it in Explore, and browse kept runs. The forecast needs a scenario, so it
    solicits its prerequisites lazily, in order: no Profile -> build the Profile first; a Profile but no
    *complete* scenario -> build one (or resume a half-built one); otherwise the chooser runs a complete
    one. Setup flows land on the Scenarios page when done; the user returns via the nav."""

    def get( self, request ):
        return render( request, _HUB_TEMPLATE, self._context( request ) )

    def post( self, request ):                             # "Run forecast": project a complete scenario
        organization   = request.organization
        profile_record = completed_profile( organization )
        complete, _drift_blocked, _in_progress = self._scenarios( organization, profile_record )
        form = ForecastForm( request.POST, scenarios = complete )
        if profile_record is None or not form.is_valid():
            return render( request, _HUB_TEMPLATE, self._context( request, form = form ) )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization,
            usage_role = UsageRole.SAVED )
        _remember_selection( request, form, scenario_record )
        scenario = load_scenario( scenario_record )
        frame    = resolve_frame(
            effective_date = profile_record.effective_date,
            start_choice   = form.cleaned_data[ 'start_from' ],
            duration_years = form.cleaned_data[ 'duration_years' ],
            granularity    = GRANULARITY[ form.cleaned_data[ 'interval' ] ] )
        try:
            with transaction.atomic():
                run = run_and_capture(
                    organization = organization, profile = load_profile( profile_record ),
                    plans = scenario.plans, assumptions = scenario.assumptions, frame = frame,
                    label = run_title( scenario_record.label, timezone.localtime() ),
                    source_label = scenario_record.label )
                PlanningResultRecord.objects.create(
                    organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                    run = run, label = run.label )
        except ValueError as error:
            # Run-time input errors surface inline rather than as a 500: `materialize`'s validation and
            # the books' `DuplicateAccountHandleError` (a ValueError) both land here.
            return render(
                request, _HUB_TEMPLATE, self._context( request, form = form, error = str( error ) ) )
        return redirect( 'run_results', run_uuid = run.uuid )

    @staticmethod
    def _scenarios( organization, profile_record ):
        """The org's (complete, drift_blocked, in_progress) scenarios against the current profile -- all
        empty when there is no *complete* profile yet (nothing is runnable, and the profile gate leads
        first)."""
        if profile_record is None:
            return list(), list(), list()
        return partition_scenarios( organization, profile_record )

    def _context( self, request, form = None, error = None ) -> dict:
        organization   = request.organization
        profile_record = completed_profile( organization )   # completeness, not mere existence
        complete, drift_blocked, in_progress = self._scenarios( organization, profile_record )
        exploration    = scenario_exploration( organization )
        # The one in-progress scenario the gate leads into -- a started one to resume, else the untouched
        # Default to build. Either way the CTA enters *its* build flow (the Scenarios page is the only
        # place that composes an entirely new scenario); `started` only drives the resume-vs-build wording.
        started_scenario = next( ( s for s in in_progress if scenario_started( s ) ), None )
        return {
            'has_profile'  : profile_record is not None,   # a *complete* profile
            'effective_date' : profile_record.effective_date if profile_record else None,
            'scenarios'    : complete,                     # the chooser offers only runnable scenarios
            'drift_scenarios' : self._drift_notices( drift_blocked, profile_record ),
            'build_scenario'         : started_scenario or ( in_progress[ 0 ] if in_progress else None ),
            'build_scenario_started' : started_scenario is not None,
            'resume'       : self._live_resume( exploration, profile_record ),
            # One setup form; both actions submit it -- Run once (this view's POST) and Run & Explore (the
            # workspace). A run whose submission erred is re-rendered in place with its messages.
            'form'         : form or ForecastForm(
                scenarios = complete, initial = self._selection_defaults( request, profile_record ) ),
            'saved_runs'   : self._saved_runs( organization ),
            'error'        : error,
        }

    @staticmethod
    def _saved_runs( organization ) -> list:
        """The org's saved forecast runs, newest first, each paired with a cheap display digest read from
        its captured run JSON (no books load) so the list is scannable -- horizon and outcome per row."""
        records = PlanningResultRecord.objects.select_related( 'run' ).filter(
            organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
            usage_role = UsageRole.SAVED ).order_by( '-created_datetime' )
        return [ { 'result': record, 'digest': _saved_run_digest( record.run ) } for record in records ]

    @staticmethod
    def _drift_notices( drift_blocked, profile_record ) -> list:
        """Each drift-blocked scenario as `{label, drift}` for the hub -- its stale references and
        one-click reconcile from the shared `inputs.drift` notice, rendered through the shared
        scenario-drift pane (the same one the Scenarios cards and Plans flow use)."""
        if profile_record is None:
            return list()
        profile = load_profile( profile_record )
        return [ { 'label' : scenario.label, 'drift' : plans_drift( profile, scenario.plans ) }
                 for scenario in drift_blocked ]

    @classmethod
    def _live_resume( cls, exploration, profile_record ):
        """The resume-exploration notice, or None -- suppressed when there is no exploration or when the
        one in progress has drifted against the current profile: either its `source` (the scenario it is
        anchored to, which the notice names and the drift block flags) or its `working` copy references
        something the profile no longer has. So the hub never offers to resume an exploration of a
        drift-blocked scenario alongside the block telling the user to reconcile it."""
        if exploration is None or profile_record is None:
            return None
        if cls._drifted( profile_record, exploration.source ) or \
           cls._drifted( profile_record, exploration.working ):
            return None
        return cls._resume( exploration )

    @staticmethod
    def _drifted( profile_record, scenario_record ) -> bool:
        """Whether a scenario has a Plans->Profile drift issue against `profile_record`."""
        return any( issue.is_drift for issue in scenario_readiness( profile_record, scenario_record ) )

    @staticmethod
    def _resume( exploration ) -> dict:
        """The in-progress exploration surfaced on the hub: just its anchor scenario. The hub names it and
        offers Resume; what has diverged from the anchor is shown on the Explore workspace itself, not
        repeated here."""
        return { 'source': exploration.source }

    @staticmethod
    def _selection_defaults( request, profile_record ) -> dict:
        """The scenario and frame the user last chose, from the session; an unset value falls through to a
        sensible default -- the first scenario, the built-in start/interval, and an age-based duration that
        runs the household to the planning horizon. The stored duration always wins once set, so the
        computed one is only the first-time default, never an override of a duration already chosen."""
        state    = request.session_state
        defaults = { key: value for key, value in {
            'scenario'   : state.current_scenario_uuid,
            'start_from' : state.forecast_start_from,
            'interval'   : state.forecast_interval,
        }.items() if value is not None }
        stored = state.forecast_duration_years
        defaults[ 'duration_years' ] = (
            stored if stored is not None else _default_duration_years( profile_record ) )
        return defaults


@method_decorator( ensure_organization, name = 'dispatch' )
class RunResultsView( View ):
    """`/run/<uuid>/` -- a captured run: its Books of Account as a drill-down table
    (through the user's column lens), plus the stop condition and notices from the persisted
    result."""

    # The full-page template; overridable so a wrapper (the sample-data tour) can render the same run
    # output under a different shell.
    results_template = _RESULTS_TEMPLATE

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        run = from_json_data( ProjectionRun, record.data )
        books = BooksOfAccountRepository().load( record.books )
        dated_notices = [ ( step.end_date.year, notice )
                          for step in run.result.steps for notice in step.notices ]
        worst_severity = max( ( notice.severity for _, notice in dated_notices ),
                              default = None, key = lambda severity : severity.value )
        context = {
            'record'           : record,
            'stopped_early'    : run.result.stopped_early,
            'notices'          : [ self._notice_row( year, notice )
                                   for year, notice in dated_notices ],
            # The worst severity present tints the collapsed toggle, previewing what is inside.
            'notices_severity' : str( worst_severity ) if worst_severity else None,
        }
        context.update( run_outcome( run, books ) )
        context.update( run_books_table_context( request, run, books ) )
        # A compact balances sparkline beside the summary; the full charts open in a
        # modal (RunChartsModalView), so only the thumbnail is built for the page.
        context[ 'balances_thumbnail' ] = balances_chart( run, books, chrome = CHROME_SPARKLINE )
        context.update( self._extra_context( request ) )
        return render( request, self.results_template, context )

    def _extra_context( self, request ) -> dict:
        """Extra template context a wrapper wants merged in (e.g. the sample-data tour marking its active
        step for the shell's step-nav). Empty by default; overridden alongside `results_template`."""
        return {}

    @staticmethod
    def _notice_row( year, notice ):
        """A notice flattened for display. `severity` is the lowercase token ('info'/'warning')
        that drives the row's colour classes; `severity_label` is its human title."""
        return {
            'year'           : year,
            'kind'           : notice.kind.label,
            'severity'       : str( notice.severity ),
            'severity_label' : notice.severity.label,
            'amount'         : notice.amount,
            'detail'         : notice.detail,
        }


@method_decorator( ensure_organization, name = 'dispatch' )
class RenameRunView( View ):
    """`/run/<uuid>/rename/` -- rename a captured run from the results page's inline editor. Renames the run
    record itself -- the one label the results page and the hub both show -- and saves silently (a blank
    name is ignored). Runs need not be uniquely named, so there is no conflict check."""

    def post( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        label = request.POST.get( 'label', '' ).strip()
        if label:
            record.label = label
            record.save()
        return antinode.response()


@method_decorator( ensure_organization, name = 'dispatch' )
class RunDiscardConfirmView( ModalView ):
    """`/run/<uuid>/discard-confirm/` -- the styled confirm dialog for discarding a run, opened from the
    run page's Discard and the hub's per-row delete (both remove the same saved run). Its Discard action
    posts to `delete_run`."""

    def get_template_name( self ):
        return _DISCARD_CONFIRM_TEMPLATE

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        return self.modal_response( request, context = { 'record': record } )


@method_decorator( ensure_organization, name = 'dispatch' )
class RunChartsModalView( ModalView ):
    """`/run/<uuid>/charts/` -- the wide modal opened from the summary's balances
    thumbnail: the fully-labelled charts split by scale -- balances (net worth,
    assets, liabilities) and annual flows (income, expenses) -- each with a legend."""

    def get_template_name( self ):
        return _CHARTS_MODAL_TEMPLATE

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        run   = from_json_data( ProjectionRun, record.data )
        books = BooksOfAccountRepository().load( record.books )
        context = {
            'record'         : record,
            'balances_chart' : balances_chart(
                run, books, chrome = CHROME_FULL, width = 720, height = 300 ),
            'flows_chart'    : flows_chart(
                run, books, chrome = CHROME_FULL, width = 720, height = 300 ),
        }
        return self.modal_response( request, context = context )


@method_decorator( ensure_organization, name = 'dispatch' )
class RunColumnChartModalView( ModalView ):
    """`/run/<uuid>/column-chart/?column=<token>` -- the modal opened from a books-table
    column's "Chart" action: that column's value over time, with its immediate children
    beside it when it is a small-enough rollup."""

    def get_template_name( self ):
        return _COLUMN_CHART_MODAL_TEMPLATE

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        token = request.GET.get( 'column' )
        if not token:
            raise Http404( 'No column specified.' )
        run   = from_json_data( ProjectionRun, record.data )
        books = BooksOfAccountRepository().load( record.books )
        try:
            chart = column_chart( run, books, BooksColumnKey( token ), width = 720, height = 320 )
        except ValueError as error:
            raise Http404( str( error ) )
        return self.modal_response( request, context = { 'record': record, 'column_chart': chart } )


@method_decorator( ensure_organization, name = 'dispatch' )
class EnterExploreView( InputGatedMixin, View ):
    """`/plan/financial-forecast/explore/enter/` -- from the hub, start exploring the chosen saved scenario,
    then redirect to the workspace. Always starts fresh: it re-seeds the sandbox from the scenario's *current*
    inputs and clears the prior run history, so an edit to the saved scenario between sessions is always
    reflected rather than resuming a stale working copy or a run computed before the change. Continuing an
    in-progress exploration with its tweaks and runs intact is the separate Resume button (a direct link to
    the workspace). The frame rides in the POSTed form and is remembered for the workspace, which lives at the
    uuid-less `/explore/`."""

    def post( self, request ):
        organization = request.organization
        form = ForecastForm( request.POST, scenarios = scenarios_for( organization ) )
        if not form.is_valid():
            return redirect( 'financial_forecast' )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization,
            usage_role = UsageRole.SAVED )
        _remember_selection( request, form, scenario_record )
        # Always start fresh from the chosen scenario's current inputs (re-seed and clear the run history),
        # so Run & Explore never resumes a stale working copy; Resume is the path that keeps tweaks and runs.
        start_fresh_exploration( organization, scenario_record )
        exploration = scenario_exploration( organization )
        # Record the chosen frame onto the exploration so the workspace projects over it (rather than a
        # session default); the workspace re-runs whenever this diverges from its latest run's frame.
        record_exploration_frame(
            exploration, form.cleaned_data[ 'start_from' ],
            form.cleaned_data[ 'duration_years' ], form.cleaned_data[ 'interval' ] )
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class ExploreView( InputGatedMixin, View ):
    """`/plan/financial-forecast/explore/` -- the exploration workspace: the working copy's inputs, an
    explicit re-run, the transient-run history, and the selected run's results table. It reads the
    organization's single in-progress exploration (uuid-less, since there is only one), whose `source` is
    the saved scenario it is anchored to -- displayed as its name, the target a save overwrites, and the
    baseline the drift diff compares against. Redirects to the hub when no exploration is in progress."""

    _TEMPLATE = 'planning/pages/explore.html'

    def get( self, request ):
        organization = request.organization
        exploration = scenario_exploration( organization )
        if exploration is None:
            return redirect( 'financial_forecast' )        # nothing to explore yet
        source  = exploration.source
        working = exploration.working
        # Produce a run for the entered frame when there is none yet (first entry) or the latest run was
        # projected over a different frame (the user changed the when-controls and resumed) -- so the
        # results shown always match the current frame without waiting on an explicit Re-run.
        frame = self._frame( request )
        runs  = list( transient_runs( organization ) )
        profile_drift = self._profile_drift( organization, runs )
        # Produce a run for a first entry or a changed frame -- but NOT once the Profile has drifted: a new
        # run would use the updated Profile and could not be compared to the pile below, so new runs pause
        # until the exploration is re-baselined on the current Profile (Start over with updated profile).
        if not runs or ( _run_frame( runs[ 0 ] ) != frame and not profile_drift ):
            run_working_scenario( organization, frame )
            runs = list( transient_runs( organization ) )
            profile_drift = self._profile_drift( organization, runs )
        selected = self._selected_run( request, runs )     # the run whose results to show (a chip or latest)
        working_inputs = load_scenario( working )
        source_inputs  = load_scenario( source )
        state    = request.session_state
        forms    = {
            'living_form' : LivingExpensesExploreForm(
                scenario = working_inputs, selected = state.explore_curated_expenses ),
            'econ_form'   : EconomicAssumptionsExploreForm(
                scenario = working_inputs, selected = state.explore_curated_rates ) }
        # Drift is measured against the saved source scenario -- exactly what an "update" would overwrite.
        drift    = value_changes( source_inputs, working_inputs )
        return render(
            request, self._TEMPLATE,
            self._context( request, source, runs, selected, forms, drift, profile_drift ) )

    def post( self, request ):                             # Re-run: project the auto-saved working scenario
        organization = request.organization
        # The dials auto-save; Re-run only re-projects them -- but not while the Profile has drifted (new
        # runs are paused until re-baselined, mirrored server-side behind the hidden Re-run button).
        if ( scenario_exploration( organization ) is not None
             and not self._profile_drift( organization, list( transient_runs( organization ) ) ) ):
            run_working_scenario( organization, self._frame( request ) )
        return redirect( 'explore' )

    def _profile_drift( self, organization, runs ) -> list:
        """The household facts that changed since the shown (latest) run was computed -- non-empty when the
        exploration's runs predate a Profile update (each run embeds the Profile it used). Because new runs
        are paused once this is non-empty, the pile stays on one Profile, so the latest run represents it."""
        if not runs:
            return list()
        current = latest_profile( organization )
        if current is None:
            return list()
        run_profile = from_json_data( ProjectionRun, runs[ 0 ].run.data ).profile
        return profile_changes( run_profile, load_profile( current ) )

    def _context( self, request, source, runs, selected, forms, drift, profile_drift ) -> dict:
        run     = from_json_data( ProjectionRun, selected.run.data )
        books   = BooksOfAccountRepository().load( selected.run.books )
        context = {
            'input_state'    : request.input_state,
            'source'         : source,        # the saved scenario being explored (its name, the save target)
            'transient_runs' : runs,
            'selected'       : selected,
            'record'         : selected.run,  # the ProjectionRunRecord the books-table column ops key on
            'stopped_early'  : run.result.stopped_early,
            'drift'          : drift,                          # curated changes vs the source scenario
            'drift_summary'  : describe_changes( drift ),
            'profile_drift'  : profile_drift,                  # Profile facts changed since these runs (pauses new runs)
            **forms,
        }
        context.update( run_outcome( run, books ) )           # horizon + ending net worth for the banner
        context.update( run_books_table_context( request, run, books ) )
        # The same balances thumbnail the results page shows -- charts are as useful while
        # exploring as on a saved run; the modal keys on `record` (the selected run), set above.
        context[ 'balances_thumbnail' ] = balances_chart( run, books, chrome = CHROME_SPARKLINE )
        return context

    @staticmethod
    def _selected_run( request, runs ):
        """The transient run whose results to show -- the one a chip names (`?run=<uuid>`), else the
        most recent."""
        run_uuid = request.GET.get( 'run' )
        if run_uuid:
            for result in runs:
                if str( result.run.uuid ) == run_uuid:
                    return result
        return runs[ 0 ]

    def _frame( self, request ) -> ForecastFrame:
        """The frame the exploration's runs project over -- resolved from the frame recorded on the
        exploration (not the session, which only seeds the hub form's defaults). The `or` fallbacks cover
        only a legacy exploration entered before the frame was recorded; entry always records it now."""
        exploration = scenario_exploration( request.organization )
        profile     = latest_profile( request.organization )
        return resolve_frame(
            effective_date = profile.effective_date,
            start_choice   = exploration.frame_start_from or 'effective',
            duration_years = exploration.frame_duration_years or 40,
            granularity    = GRANULARITY.get( exploration.frame_interval or 'year', GRANULARITY[ 'year' ] ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class ExploreRestartView( InputGatedMixin, View ):
    """`/plan/financial-forecast/explore/restart/` -- re-baseline the in-progress exploration on the current
    Profile: re-seed the working copy from the anchor's current inputs and clear the run history, then let the
    workspace re-run. The workspace's answer to Profile drift -- the runs were computed against an earlier
    Profile, so this starts the comparison over on the updated one (the same primitive Run & Explore uses)."""

    def post( self, request ):
        organization = request.organization
        exploration = scenario_exploration( organization )
        if exploration is not None:
            start_fresh_exploration( organization, exploration.source )
        return redirect( 'explore' )


class _ExploreSectionAutosaveView( InputGatedMixin, View ):
    """Base for a self-saving Explore input section: a valid edit is applied to the working scenario and
    saved silently (the `js-autosave` pattern the inputs panes use), so typing is undisturbed; an
    incomplete or invalid entry simply is not saved. Explore edits values only, so nothing structural
    changes and the response is always the silent, no-op antinode acknowledgement -- Re-run re-projects
    the accumulated edits when the user asks."""

    form_class = None

    def post( self, request ):
        organization = request.organization
        working = working_scenario( organization )
        if working is not None:
            current = load_scenario( working )
            form    = self.form_class( request.POST, scenario = current )
            if form.is_valid():
                overwrite_working( organization, form.apply( current ) )
        return antinode.response()


class ExplorePlansAutosaveView( _ExploreSectionAutosaveView ):
    """`.../explore/plans/` -- self-save the Living Expenses dials into the working scenario."""

    form_class = LivingExpensesExploreForm


class ExploreAssumptionsAutosaveView( _ExploreSectionAutosaveView ):
    """`.../explore/assumptions/` -- self-save the Economic dials into the working scenario."""

    form_class = EconomicAssumptionsExploreForm


class ExploreCurationView( InputGatedMixin, View ):
    """`.../explore/curate/` -- persist which inputs a section keeps visible when collapsed (the curated
    subset). Visual only -- saved silently to the session when the user closes the picker, keyed by section.
    Unknown sections are ignored."""

    _SESSION_FIELD = {
        'expenses' : 'explore_curated_expenses',
        'rates'    : 'explore_curated_rates',
    }

    def post( self, request ):
        field = self._SESSION_FIELD.get( request.POST.get( 'section' ) )
        if field is not None:
            keys = [ key for key in ( request.POST.get( 'keys' ) or '' ).split( ',' ) if key ]
            setattr( request.session_state, field, keys )
            request.session_state.to_session( request )
        return antinode.response()


@method_decorator( ensure_organization, name = 'dispatch' )
class SaveView( InputGatedMixin, View ):
    """`.../explore/save/` -- persist the sandbox from the Save-changes modal. `save_mode` is 'update' (write
    the changes back into the anchor -- both components overwrite in place) or 'new' (branch a scenario named
    `name`, copying the components that diverged and reusing the unchanged ones -- `branch_destinations`
    decides that, so the user makes no per-component choice). Either way it drives the one `save_working`
    primitive."""

    def post( self, request ):
        organization = request.organization
        exploration  = scenario_exploration( organization )
        if exploration is not None:
            if request.POST.get( 'save_mode' ) == 'new':
                destinations = branch_destinations(
                    load_scenario( exploration.source ), load_scenario( exploration.working ) )
                name = request.POST.get( 'name', '' )
            else:                                          # update the existing scenario: overwrite both
                destinations = { component: OVERWRITE for component in ( 'plans', 'assumptions' ) }
                name = ''
            save_working( organization, exploration.source, destinations, name )
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class ExploreSaveModalView( ModalView ):
    """`.../explore/save-dialog/` -- the styled Save-changes dialog opened from the workspace's sticky bar.
    Presents the changes against the anchor for review, then the choice to update the anchor in place or
    branch a new scenario (whose diverged components are copied and unchanged ones reused -- decided for the
    user). Its Save posts to `explore_save` (`SaveView`), which drives the same `save_working` primitive."""

    def get_template_name( self ):
        return _EXPLORE_SAVE_TEMPLATE

    def get( self, request ):
        exploration = scenario_exploration( request.organization )
        if exploration is None:
            raise Http404( 'No exploration in progress.' )
        source_inputs  = load_scenario( exploration.source )
        working_inputs = load_scenario( exploration.working )
        drift = value_changes( source_inputs, working_inputs )
        usage = component_usage( exploration.source )
        return self.modal_response( request, context = {
            'source'        : exploration.source,
            'drift'         : drift,
            'drift_summary' : describe_changes( drift ),
            # Open in "save as new" when an in-place update would write a change into a set another scenario
            # shares -- branching copies that changed component instead, leaving the shared set untouched.
            'default_new'   : any(
                usage[ component ] and getattr( working_inputs, component ) != getattr( source_inputs, component )
                for component in ( 'plans', 'assumptions' ) ),
        } )


@method_decorator( ensure_organization, name = 'dispatch' )
class ResetExploreView( InputGatedMixin, View ):
    """`.../explore/reset/` -- discard the sandbox's changes and run history, starting the exploration over
    from its anchor. The explicit hard restart: re-entering the same scenario from the hub resumes rather
    than resets (so a refresh is safe), and this is how the user asks to begin again on the same anchor."""

    def post( self, request ):
        organization = request.organization
        exploration  = scenario_exploration( organization )
        if exploration is not None:
            start_fresh_exploration( organization, exploration.source )   # re-seed anchor, clear runs
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class KeepRunView( InputGatedMixin, View ):
    """`.../explore/keep-run/` -- retain a transient run: mark it SAVED so it is kept (and drops out of the
    transient strip and its prune) rather than churned away."""

    def post( self, request ):
        organization = request.organization
        result = get_object_or_404(
            PlanningResultRecord, run__uuid = request.POST.get( 'run' ), organization = organization )
        result.usage_role = UsageRole.SAVED
        result.save( update_fields = [ 'usage_role', 'updated_datetime' ] )
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class DeleteRunView( InputGatedMixin, View ):
    """`.../financial-forecast/runs/<uuid>/delete/` -- delete a saved forecast run from the hub's
    Saved-runs list, dropping its captured books. Scoped to the org's SAVED forecast results, so a stale
    or foreign uuid 404s rather than deleting."""

    def post( self, request, run_uuid ):
        result = get_object_or_404(
            PlanningResultRecord, run__uuid = run_uuid, organization = request.organization,
            feature = PlanningFeature.FINANCIAL_FORECAST, usage_role = UsageRole.SAVED )
        delete_runs( [ result ] )
        return redirect( 'financial_forecast' )


@method_decorator( ensure_organization, name = 'dispatch' )
class ProjectionRunBooksTableView( PermitsReadonlyMutation, View ):
    """`/run/<uuid>/books/` -- apply a column operation to the user's BooksTable lens
    (expand/collapse/hide/add/move), persist it, and swap the re-rendered table fragment.

    Opted out of the read-only write-gate: the column operation persists only the member's own
    per-user session lens (`books_table_definition`), never organization data, so a read-only member
    may reshape and drill into their view of the results like anyone else."""

    def post( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        run = from_json_data( ProjectionRun, record.data )
        books = BooksOfAccountRepository().load( record.books )
        context = apply_run_books_operation(
            request, run, books, request.POST.get( 'op' ), request.POST.get( 'column' ) )
        context[ 'record' ] = record
        fragment = render_to_string( _BOOKS_TABLE_TEMPLATE, context, request = request )
        return antinode.response( replace_map = { 'books-table': fragment } )


@method_decorator( ensure_organization, name = 'dispatch' )
class BooksTableJournalView( ModalView ):
    """`/run/<uuid>/books/account/<uuid>/journal/` -- one account's Journal (its entries in
    transaction order) in a modal, reached from that account's results column."""

    def get_template_name( self ):
        return _JOURNAL_TEMPLATE

    def get( self, request, run_uuid, account_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        bookkeeper = Bookkeeper( BooksOfAccountRepository().load( record.books ) )
        account = bookkeeper.chart.account_by_uuid( account_uuid )
        if account is None:
            raise Http404( 'No such account in this run.' )
        return self.modal_response( request, context = {
            'record'  : record,
            'account' : account,
            'entries' : self._entries( bookkeeper, account ),
        } )

    @staticmethod
    def _entries( bookkeeper, account ):
        """The account's journal rows: for an appreciating holding, its own postings folded with its
        valuation companion's so the running balance tracks market value; for any other account, its
        plain per-account journal."""
        valuation_account = bookkeeper.chart.valuation_of( account )
        journal           = bookkeeper.journal
        if valuation_account is None:
            return journal.account_entries( account )
        return journal.market_value_entries( account, valuation_account )
