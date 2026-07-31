"""The Financial Forecast hub and per-run results.

The hub (`/plan/financial-forecast/`) orchestrates the flow without re-implementing the profile or
plans forms: it links out to them, makes the forecast bundle explicit (which profile, which plans,
which assumptions, the frame), runs it, and lists past runs. The results page (`/run/<uuid>/`) shows
a captured run -- the net-worth trajectory derived from its persisted books, whether it stopped
early, and the notices. The interview and the input editors live in the `inputs` app.
"""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from user.decorators import ensure_organization

from common import antinode
from common.async_view import ModalView
from common.dataclass_json import from_json_data

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.mixins import InputGatedMixin
from ucfp.inputs.models import ScenarioRecord
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.state import completed_profile
from ucfp.inputs.scenarios.exploration import (
    overwrite_working, save_working_as_scenario, save_working_over_scenario, scenario_exploration,
    working_scenario )
from ucfp.inputs.scenarios.repository import load_scenario, scenarios_for

from .books_table import apply_run_books_operation, run_books_table_context
from .enums import PlanningFeature
from .explore import enter_explore, run_working_scenario, transient_runs
from .explore_diff import describe_changes, value_changes
from .explore_sections import EconomicAssumptionsExploreForm, LivingExpensesExploreForm
from .forms import ForecastForm, GRANULARITY, resolve_frame
from .gating import partition_scenarios
from .materialization import ForecastFrame
from .models import ProjectionRunRecord, PlanningResultRecord
from .orchestration import run_and_capture
from .schemas import ProjectionRun

_HUB_TEMPLATE = 'planning/pages/financial_forecast.html'
_RESULTS_TEMPLATE = 'planning/pages/run_results.html'
_BOOKS_TABLE_TEMPLATE = 'planning/pages/run_books_table.html'
_JOURNAL_TEMPLATE = 'planning/modals/account_journal.html'
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
        complete, _in_progress = self._scenarios( organization, profile_record )
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
                    plans = scenario.plans, assumptions = scenario.assumptions,
                    frame = frame, label = scenario_record.label )
                PlanningResultRecord.objects.create(
                    organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                    run = run, label = run.label )
        except ValueError as error:
            return render(
                request, _HUB_TEMPLATE, self._context( request, form = form, error = str( error ) ) )
        return redirect( 'run_results', run_uuid = run.uuid )

    @staticmethod
    def _scenarios( organization, profile_record ):
        """The org's (complete, in_progress) scenarios against the current profile -- both empty when there
        is no *complete* profile yet (nothing is runnable, and the profile gate leads first)."""
        if profile_record is None:
            return list(), list()
        return partition_scenarios( organization, profile_record )

    def _context( self, request, form = None, error = None ) -> dict:
        organization   = request.organization
        profile_record = completed_profile( organization )   # completeness, not mere existence
        complete, in_progress = self._scenarios( organization, profile_record )
        exploration    = scenario_exploration( organization )
        return {
            'has_profile'  : profile_record is not None,   # a *complete* profile
            'scenarios'    : complete,                     # the chooser offers only runnable scenarios
            'in_progress'  : in_progress,                  # half-built scenarios to resume
            'resume'       : self._resume( exploration ) if exploration is not None else None,
            'form'         : form or ForecastForm(
                scenarios = complete, initial = self._selection_defaults( request ) ),
            'results'      : PlanningResultRecord.objects.select_related( 'run' ).filter(
                organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                usage_role = UsageRole.SAVED ).order_by( '-created_datetime' ),
            'error'        : error,
        }

    @staticmethod
    def _resume( exploration ) -> dict:
        """The in-progress exploration surfaced on the hub: its anchor and how far the sandbox has diverged,
        so Resume can say what it returns to -- the anchor as-is, or a variation of it."""
        drift = value_changes( load_scenario( exploration.source ), load_scenario( exploration.working ) )
        return {
            'source'       : exploration.source,
            'drift_summary': describe_changes( drift ),
            'changed'      : bool( drift ) }

    @staticmethod
    def _selection_defaults( request ) -> dict:
        """The scenario and frame the user last chose, from the session; an unset (or stale) value falls
        through to the form's own default -- the first scenario, the built-in frame -- rather than blanks."""
        state = request.session_state
        return { key: value for key, value in {
            'scenario'       : state.current_scenario_uuid,
            'start_from'     : state.forecast_start_from,
            'duration_years' : state.forecast_duration_years,
            'interval'       : state.forecast_interval,
        }.items() if value is not None }


@method_decorator( ensure_organization, name = 'dispatch' )
class RunResultsView( View ):
    """`/run/<uuid>/` -- a captured run: its Books of Account as a drill-down table
    (through the user's column lens), plus the stop condition and notices from the persisted
    result."""

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        run = from_json_data( ProjectionRun, record.data )
        books = BooksOfAccountRepository().load( record.books )
        context = {
            'record'        : record,
            'stopped_early' : run.result.stopped_early,
            'notices'       : [ ( step.end_date.year, notice.kind.label,
                                  notice.severity.label, notice.amount, notice.detail )
                                for step in run.result.steps for notice in step.notices ],
        }
        context.update( run_books_table_context( request, run, books ) )
        return render( request, _RESULTS_TEMPLATE, context )


@method_decorator( ensure_organization, name = 'dispatch' )
class EnterExploreView( InputGatedMixin, View ):
    """`/plan/financial-forecast/explore/enter/` -- from the hub, start or resume exploring the chosen saved
    scenario, then redirect to the workspace. Idempotent: re-entering the scenario already in progress
    resumes it (tweaks and run history intact); choosing a different one re-seeds the sandbox and anchors to
    it. The frame rides in the POSTed form and is remembered for the workspace, which lives at the uuid-less
    `/explore/`. A hard restart of the same scenario is the workspace's own Reset, not a re-entry."""

    def post( self, request ):
        organization = request.organization
        form = ForecastForm( request.POST, scenarios = scenarios_for( organization ) )
        if not form.is_valid():
            return redirect( 'financial_forecast' )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization,
            usage_role = UsageRole.SAVED )
        _remember_selection( request, form, scenario_record )
        exploration = scenario_exploration( organization )
        if exploration is None or exploration.source_id != scenario_record.id:
            enter_explore( organization, scenario_record )     # new or switched anchor: seed + clear runs
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
        runs = list( transient_runs( organization ) )
        if not runs:                                       # first entry: produce the initial run
            run_working_scenario( organization, self._frame( request ) )
            runs = list( transient_runs( organization ) )
        selected = self._selected_run( request, runs )     # the run whose results to show (a chip or latest)
        working_inputs = load_scenario( working )
        state    = request.session_state
        forms    = {
            'living_form' : LivingExpensesExploreForm(
                scenario = working_inputs, selected = state.explore_curated_expenses ),
            'econ_form'   : EconomicAssumptionsExploreForm(
                scenario = working_inputs, selected = state.explore_curated_rates ) }
        # Drift is measured against the saved source scenario -- exactly what an "update" would overwrite.
        drift    = value_changes( load_scenario( source ), working_inputs )
        return render(
            request, self._TEMPLATE, self._context( request, source, runs, selected, forms, drift ) )

    def post( self, request ):                             # Re-run: project the auto-saved working scenario
        organization = request.organization
        if scenario_exploration( organization ) is not None:   # the dials auto-save; Re-run only re-projects
            run_working_scenario( organization, self._frame( request ) )
        return redirect( 'explore' )

    def _context( self, request, source, runs, selected, forms, drift ) -> dict:
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
            **forms,
        }
        context.update( run_books_table_context( request, run, books ) )
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
        state   = request.session_state
        profile = latest_profile( request.organization )
        return resolve_frame(
            effective_date = profile.effective_date,
            start_choice   = state.forecast_start_from or 'effective',
            duration_years = state.forecast_duration_years or 40,
            granularity    = GRANULARITY.get( state.forecast_interval or 'year', GRANULARITY[ 'year' ] ) )


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
class UpdateScenarioView( InputGatedMixin, View ):
    """`.../explore/update-scenario/` -- overwrite the explored saved scenario (the exploration's anchor)
    with the working copy's current inputs. The common 'save my changes' action, distinct from minting a
    new scenario; the anchor's name is unchanged and the exploration stays on it."""

    def post( self, request ):
        organization = request.organization
        exploration  = scenario_exploration( organization )
        if exploration is not None:
            save_working_over_scenario( organization, exploration.source )
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class SaveScenarioView( InputGatedMixin, View ):
    """`.../explore/save-scenario/` -- promote the working scenario to a new, separately named saved
    scenario (a copy; the working copy keeps churning). The exploration re-anchors to the new scenario, so a
    subsequent update targets it rather than the one it was forked from."""

    def post( self, request ):
        organization = request.organization
        exploration  = scenario_exploration( organization )
        if exploration is not None:
            name = ( request.POST.get( 'name' ) or '' ).strip() or 'Saved scenario'
            save_working_as_scenario( organization, name, exploration.source )
        return redirect( 'explore' )


@method_decorator( ensure_organization, name = 'dispatch' )
class ResetExploreView( InputGatedMixin, View ):
    """`.../explore/reset/` -- discard the sandbox's changes and run history, starting the exploration over
    from its anchor. The explicit hard restart: re-entering the same scenario from the hub resumes rather
    than resets (so a refresh is safe), and this is how the user asks to begin again on the same anchor."""

    def post( self, request ):
        organization = request.organization
        exploration  = scenario_exploration( organization )
        if exploration is not None:
            enter_explore( organization, exploration.source )   # re-seed from the anchor + clear the runs
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
class ProjectionRunBooksTableView( View ):
    """`/run/<uuid>/books/` -- apply a column operation to the user's BooksTable lens
    (expand/collapse/hide/add/move), persist it, and swap the re-rendered table fragment."""

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
