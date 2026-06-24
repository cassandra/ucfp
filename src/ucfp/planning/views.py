"""The retirement-planning hub and per-run results.

The hub (`/planning/retirement/`) orchestrates the flow without re-implementing the profile or
scenario forms: it links out to them, makes the forecast bundle explicit (which profile, which
scenario, the frame), runs it, and lists past runs. The results page (`/planning/run/<uuid>/`)
shows a captured run -- the net-worth trajectory derived from its persisted books, whether it
stopped early, and the notices.
"""
from datetime import timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from common.dataclass_json import from_json_data

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.profile.models import ProfileRecord
from ucfp.profile.repository import load_profile, profiles_for
from ucfp.scenario.models import ScenarioRecord
from ucfp.scenario.repository import load_scenario, scenarios_for

from .forms import GRANULARITY, RunForm
from .materialization import ForecastFrame
from .models import ProjectionRunRecord
from .orchestration import run_and_capture
from .schemas import ProjectionRun

_HUB_TEMPLATE = 'planning/pages/retirement_hub.html'
_RESULTS_TEMPLATE = 'planning/pages/run_results.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class RetirementPlanningView( View ):
    """`/planning/retirement/` -- the hub: choose the profile + scenario + frame, run, and browse
    past runs."""

    def get( self, request ):
        return render( request, _HUB_TEMPLATE, self._context( request ) )

    def post( self, request ):
        organization = request.organization
        form = RunForm(
            request.POST,
            profiles = profiles_for( organization ), scenarios = scenarios_for( organization ) )
        if not form.is_valid():
            return render( request, _HUB_TEMPLATE, self._context( request, form = form ) )
        profile_record  = get_object_or_404(
            ProfileRecord, uuid = form.cleaned_data[ 'profile' ], organization = organization )
        scenario_record = get_object_or_404(
            ScenarioRecord, uuid = form.cleaned_data[ 'scenario' ], organization = organization )
        request.session_state.current_scenario_uuid = str( scenario_record.uuid )
        request.session_state.to_session( request )
        try:
            run = run_and_capture(
                organization, load_profile( profile_record ), load_scenario( scenario_record ),
                self._frame( profile_record, form ), label = scenario_record.label )
        except ValueError as error:
            return render(
                request, _HUB_TEMPLATE, self._context( request, form = form, error = str( error ) ) )
        return redirect( 'run_results', run_uuid = run.uuid )

    def _frame( self, profile_record, form ) -> ForecastFrame:
        start = profile_record.effective_date
        end = start.replace( year = start.year + form.cleaned_data[ 'duration_years' ] ) - timedelta( days = 1 )
        return ForecastFrame(
            start_date = start, end_date = end,
            granularity = GRANULARITY[ form.cleaned_data[ 'interval' ] ] )

    def _context( self, request, form = None, error = None ) -> dict:
        organization = request.organization
        profiles  = profiles_for( organization )
        scenarios = scenarios_for( organization )
        return {
            'has_profile' : profiles.exists(),
            'has_scenario': scenarios.exists(),
            'form'        : form or RunForm( profiles = profiles, scenarios = scenarios ),
            'runs'        : ProjectionRunRecord.objects.filter(
                organization = organization ).order_by( '-created_datetime' ),
            'error'       : error,
        }


@method_decorator( ensure_organization, name = 'dispatch' )
class RunResultsView( View ):
    """`/planning/run/<uuid>/` -- a captured run: net worth derived from its books, plus the
    stop condition and notices from the persisted result."""

    def get( self, request, run_uuid ):
        record = get_object_or_404(
            ProjectionRunRecord, uuid = run_uuid, organization = request.organization )
        run = from_json_data( ProjectionRun, record.data )
        ledger = Bookkeeper( BooksOfAccountRepository().load( record.books ) ).ledger
        return render( request, _RESULTS_TEMPLATE, {
            'record'        : record,
            'stopped_early' : run.result.stopped_early,
            'net_worth_rows': [ ( step.end_date.year, ledger.net_worth( through = step.end_date ) )
                                for step in run.result.steps ],
            'notices'       : [ ( step.end_date.year, notice.kind.label,
                                  notice.severity.label, notice.amount )
                                for step in run.result.steps for notice in step.notices ],
        } )
