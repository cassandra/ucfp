"""The Financial Forecast hub and per-run results.

The hub (`/plan/financial-forecast/`) orchestrates the flow without re-implementing the profile or
plans forms: it links out to them, makes the forecast bundle explicit (which profile, which plans,
which assumptions, the frame), runs it, and lists past runs. The results page (`/run/<uuid>/`) shows
a captured run -- the net-worth trajectory derived from its persisted books, whether it stopped
early, and the notices. The guided interview and the input editors live in the `inputs` app.
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
from ucfp.inputs.scenarios.repository import (
    load_scenario, save_working_as_scenario, scenarios_for, set_working_scenario, working_scenario )

from .books_table import apply_run_books_operation, run_books_table_context
from .enums import PlanningFeature
from .explore import enter_explore, run_scenario, run_working_scenario, transient_runs
from .explore_diff import curated_changes, describe_changes
from .explore_sections import EconomicAssumptionsExploreForm, LivingExpensesExploreForm
from .forms import ForecastForm, GRANULARITY, resolve_frame
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


def _remember_frame( request, form ) -> None:
    """Persist the form's chosen frame to the session, so it defaults on the next hub visit and Explore
    (which reads the frame from the session) projects over the same window."""
    request.session_state.forecast_start_from     = form.cleaned_data[ 'start_from' ]
    request.session_state.forecast_duration_years = form.cleaned_data[ 'duration_years' ]
    request.session_state.forecast_interval       = form.cleaned_data[ 'interval' ]
    request.session_state.to_session( request )


class FinancialForecastView( InputGatedMixin, View ):
    """`/plan/financial-forecast/` -- the hub: pick a saved scenario and a frame, then either run it as-is
    (this view's POST) or open it in Explore (the `Explore` button posts the same form to
    `EnterExploreView`), and browse kept runs. A scenario is the run-ready unit (a validated Plans +
    Assumptions bundle); the hub only *selects* one -- it never builds or edits scenarios. With none yet,
    it points at the (not-yet-built) scenario builder rather than offering a run."""

    def get( self, request ):
        return render( request, _HUB_TEMPLATE, self._context( request ) )

    def post( self, request ):                             # "Run forecast": project the scenario as-is
        organization = request.organization
        form = ForecastForm( request.POST, scenarios = scenarios_for( organization ) )
        if not form.is_valid():
            return render( request, _HUB_TEMPLATE, self._context( request, form = form ) )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization,
            usage_role = UsageRole.SAVED )
        profile_record = latest_profile( organization )
        if profile_record is None:
            return render( request, _HUB_TEMPLATE, self._context(
                request, form = form, error = 'Set up a profile before running a forecast.' ) )
        _remember_frame( request, form )
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

    def _context( self, request, form = None, error = None ) -> dict:
        organization = request.organization
        scenarios = scenarios_for( organization )
        return {
            'scenarios' : scenarios,
            'form'      : form or ForecastForm(
                scenarios = scenarios, initial = self._frame_defaults( request ) ),
            'results'   : PlanningResultRecord.objects.select_related( 'run' ).filter(
                organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                usage_role = UsageRole.SAVED ).order_by( '-created_datetime' ),
            'error'     : error,
        }

    @staticmethod
    def _frame_defaults( request ) -> dict:
        """The frame the user last ran, from the session; an unset field falls through to the form's own
        default rather than being blanked."""
        state = request.session_state
        return { key: value for key, value in {
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
    """`/plan/financial-forecast/explore/enter/` -- fork the hub's chosen saved scenario into the working
    copy and open its Explore workspace. The scenario's uuid (POSTed from the hub picker) rides in the
    workspace URL as the exploration's source, and the target a save can overwrite."""

    def post( self, request ):
        organization = request.organization
        form = ForecastForm( request.POST, scenarios = scenarios_for( organization ) )
        if not form.is_valid():
            return redirect( 'financial_forecast' )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization,
            usage_role = UsageRole.SAVED )
        _remember_frame( request, form )
        enter_explore( organization, load_scenario( scenario_record ) )
        return redirect( 'explore', scenario = scenario_record.uuid )


@method_decorator( ensure_organization, name = 'dispatch' )
class ExploreView( InputGatedMixin, View ):
    """`/plan/financial-forecast/explore/<scenario>/` -- the exploration workspace for a saved scenario:
    the working copy's inputs, an explicit re-run, the transient-run history, and the selected run's
    results table. The `<scenario>` uuid is the exploration's source -- displayed as its name, and (in a
    later sub-step) the target a save overwrites and the baseline a drift diff compares against."""

    _TEMPLATE = 'planning/pages/explore.html'

    def get( self, request, scenario ):
        organization = request.organization
        source  = self._source( organization, scenario )
        working = working_scenario( organization )
        if working is None:
            return redirect( 'financial_forecast' )        # nothing to explore yet
        runs = list( transient_runs( organization ) )
        if not runs:                                       # first entry: produce the initial run
            run_working_scenario( organization, self._frame( request ) )
            runs = list( transient_runs( organization ) )
        selected = self._selected_run( request, runs )     # the run whose results to show (a chip or latest)
        working_inputs = load_scenario( working )
        forms    = { 'living_form' : LivingExpensesExploreForm( scenario = working_inputs ),
                     'econ_form'    : EconomicAssumptionsExploreForm( scenario = working_inputs ) }
        drift    = curated_changes( run_scenario( runs[ -1 ] ), working_inputs )  # working vs the starting run
        return render(
            request, self._TEMPLATE, self._context( request, source, runs, selected, forms, drift ) )

    def post( self, request, scenario ):                   # apply the dialed tweaks, then re-run
        organization = request.organization
        source  = self._source( organization, scenario )
        working = working_scenario( organization )
        if working is None:
            return redirect( 'financial_forecast' )
        working_inputs = load_scenario( working )
        living   = LivingExpensesExploreForm( request.POST, scenario = working_inputs )
        economic = EconomicAssumptionsExploreForm( request.POST, scenario = working_inputs )
        if living.is_valid() and economic.is_valid():
            working_inputs = economic.apply( living.apply( working_inputs ) )
            set_working_scenario( organization, working_inputs )
            run_working_scenario( organization, self._frame( request ) )
        return redirect( 'explore', scenario = source.uuid )

    @staticmethod
    def _source( organization, scenario ) -> ScenarioRecord:
        """The saved scenario this exploration is anchored to (the URL's uuid), 404 if not the org's."""
        return get_object_or_404(
            ScenarioRecord, uuid = scenario, organization = organization, usage_role = UsageRole.SAVED )

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
            'drift'          : drift,                          # curated changes vs the starting run
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


@method_decorator( ensure_organization, name = 'dispatch' )
class SaveScenarioView( InputGatedMixin, View ):
    """`.../explore/<scenario>/save-scenario/` -- promote the working scenario to a saved, named scenario
    (a copy; the working copy keeps churning as the user explores)."""

    def post( self, request, scenario ):
        organization = request.organization
        if working_scenario( organization ) is not None:
            name = ( request.POST.get( 'name' ) or '' ).strip() or 'Saved scenario'
            save_working_as_scenario( organization, name )
        return redirect( 'explore', scenario = scenario )


@method_decorator( ensure_organization, name = 'dispatch' )
class KeepRunView( InputGatedMixin, View ):
    """`.../explore/<scenario>/keep-run/` -- retain a transient run: mark it SAVED so it is kept (and drops
    out of the transient strip and its prune) rather than churned away."""

    def post( self, request, scenario ):
        organization = request.organization
        result = get_object_or_404(
            PlanningResultRecord, run__uuid = request.POST.get( 'run' ), organization = organization )
        result.usage_role = UsageRole.SAVED
        result.save( update_fields = [ 'usage_role', 'updated_datetime' ] )
        return redirect( 'explore', scenario = scenario )


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
