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
from ucfp.inputs.mixins import InputGatedMixin
from ucfp.inputs.models import ProfileRecord, PlansRecord, AssumptionsRecord
from ucfp.inputs.profile.repository import load_profile, profiles_for
from ucfp.inputs.plans.repository import load_plans, plans_for
from ucfp.inputs.assumptions.repository import assumptions_for, load_assumptions

from .books_table import apply_run_books_operation, run_books_table_context
from .enums import PlanningFeature
from .forms import GRANULARITY, RunForm, resolve_frame
from .materialization import ForecastFrame
from .models import ProjectionRunRecord, PlanningResultRecord
from .orchestration import run_and_capture
from .readiness import readiness_issues
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


class FinancialForecastView( InputGatedMixin, View ):
    """`/plan/financial-forecast/` -- the hub: choose the profile + plans + assumptions + frame, run,
    and browse past runs. `InputGatedMixin` ensures the organization and attaches `request.input_state`
    (the existence gate) that the hub shows before its run controls."""

    def get( self, request ):
        return render( request, _HUB_TEMPLATE, self._context( request ) )

    def post( self, request ):
        organization = request.organization
        form = RunForm(
            request.POST,
            profiles = profiles_for( organization ), plans = plans_for( organization ),
            assumptions = assumptions_for( organization ) )
        if not form.is_valid():
            return render( request, _HUB_TEMPLATE, self._context( request, form = form ) )
        profile_record  = get_object_or_404(
            ProfileRecord, uuid = form.cleaned_data[ 'profile' ], organization = organization )
        plans_record = get_object_or_404(
            PlansRecord, uuid = form.cleaned_data[ 'plans' ], organization = organization )
        assumptions_record = get_object_or_404(
            AssumptionsRecord, uuid = form.cleaned_data[ 'assumptions' ], organization = organization )
        profile     = load_profile( profile_record )
        plans       = load_plans( plans_record )
        assumptions = load_assumptions( assumptions_record )
        # Make the chosen bundle the current one before gating, so a readiness redirect ("continue the
        # interview") leads back to exactly these records rather than a stale session selection.
        request.session_state.current_plans_uuid       = str( plans_record.uuid )
        request.session_state.current_assumptions_uuid = str( assumptions_record.uuid )
        request.session_state.to_session( request )
        acknowledged = frozenset(
            profile_record.acknowledged_sections ).union(
            plans_record.acknowledged_sections, assumptions_record.acknowledged_sections )
        issues = readiness_issues( profile, plans, assumptions, acknowledged )
        if issues:                                             # a doomed run: guide, do not run
            return render(
                request, _HUB_TEMPLATE, self._context( request, form = form, issues = issues ) )
        try:
            with transaction.atomic():
                run = run_and_capture(
                    organization = organization,
                    profile      = profile,
                    plans        = plans,
                    assumptions  = assumptions,
                    frame        = self._frame( profile_record, form ),
                    label        = plans_record.label )
                PlanningResultRecord.objects.create(
                    organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
                    run = run, label = run.label )
        except ValueError as error:
            return render(
                request, _HUB_TEMPLATE, self._context( request, form = form, error = str( error ) ) )
        return redirect( 'run_results', run_uuid = run.uuid )

    def _frame( self, profile_record, form ) -> ForecastFrame:
        return resolve_frame(
            effective_date = profile_record.effective_date,
            start_choice   = form.cleaned_data[ 'start_from' ],
            duration_years = form.cleaned_data[ 'duration_years' ],
            granularity    = GRANULARITY[ form.cleaned_data[ 'interval' ] ] )

    def _default_selection( self, request, profiles, plans, assumptions ) -> dict:
        """The run form's default bundle: the plans and assumptions the user last selected or edited
        (from the session), each falling back to the most recent; the profile defaults to the most
        recent (the single current one). A stale session uuid simply falls through to no preselection."""
        state = request.session_state
        return {
            'profile'     : self._first_uuid( profiles ),
            'plans'       : state.current_plans_uuid or self._first_uuid( plans ),
            'assumptions' : state.current_assumptions_uuid or self._first_uuid( assumptions ),
        }

    @staticmethod
    def _first_uuid( queryset ):
        record = queryset.first()
        return str( record.uuid ) if record is not None else None

    def _context( self, request, form = None, error = None, issues = None ) -> dict:
        organization = request.organization
        profiles    = profiles_for( organization )
        plans       = plans_for( organization )
        assumptions = assumptions_for( organization )
        return {
            'input_state'     : request.input_state,
            'form'            : form or RunForm(
                profiles = profiles, plans = plans, assumptions = assumptions,
                initial = self._default_selection( request, profiles, plans, assumptions ) ),
            'results'         : PlanningResultRecord.objects.select_related( 'run' ).filter(
                organization = organization,
                feature = PlanningFeature.FINANCIAL_FORECAST ).order_by( '-created_datetime' ),
            'error'           : error,
            'readiness_issues': issues,
        }


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
