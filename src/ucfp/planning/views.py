"""The retirement-planning hub and per-run results.

The hub (`/planning/retirement/`) orchestrates the flow without re-implementing the profile or
scenario forms: it links out to them, makes the forecast bundle explicit (which profile, which
scenario, the frame), runs it, and lists past runs. The results page (`/planning/run/<uuid>/`)
shows a captured run -- the net-worth trajectory derived from its persisted books, whether it
stopped early, and the notices.
"""
from datetime import timedelta

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from common import antinode
from common.dataclass_json import from_json_data
from common.request_utils import is_ajax

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.profile.models import ProfileRecord
from ucfp.profile.repository import (
    create_profile, latest_profile, load_profile, profiles_for, save_profile )
from ucfp.scenario.models import ScenarioRecord
from ucfp.scenario.repository import (
    create_scenario, latest_scenario, load_scenario, save_scenario, scenarios_for )

from .forms import GRANULARITY, RunForm
from .interview import (
    SECTIONS, Aggregate, applicable_sections, next_section_after, section_for )
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
class InterviewHomeView( View ):
    """`/planning/interview/` -- enter the guided setup at its first section."""

    def get( self, request ):
        return redirect( 'interview_section', section = SECTIONS[ 0 ].key )


@method_decorator( ensure_organization, name = 'dispatch' )
class InterviewView( View ):
    """`/planning/interview/<section>/` -- one section of the guided setup: an antinode-swapped
    linear flow over the organization's current Profile and Scenario. A full GET renders the whole
    page; an async GET (a stepper revisit) or a POST swaps just the section pane and refreshes the
    stepper.

    On a valid POST the section is saved and the *next* section is recomputed from the now-updated
    profile -- the conditional-flow payoff. Each section merges only its own part via `apply_to`,
    so advancing (or revisiting) never clobbers another section's facts.
    """

    _PAGE_TEMPLATE    = 'planning/interview/page.html'
    _SECTION_TEMPLATE = 'planning/interview/section.html'
    _STEPPER_TEMPLATE = 'planning/interview/stepper.html'
    _SECTION_TARGET   = 'interview-section'
    _STEPPER_TARGET   = 'interview-stepper'

    def get( self, request, section ):
        current  = self._live_section( section )
        profile, scenario = self._load( request.organization, current )
        sections = applicable_sections( profile )
        form     = current.form( profile = profile, scenario = scenario )
        if is_ajax( request ):
            return self._swap( request, sections, current, form )
        return render( request, self._PAGE_TEMPLATE, self._context( sections, current, form ) )

    def post( self, request, section ):
        current = self._live_section( section )
        organization = request.organization
        profile, scenario = self._load( organization, current )
        form = current.form( request.POST, profile = profile, scenario = scenario )
        if not form.is_valid():
            return self._swap( request, applicable_sections( profile ), current, form )
        profile   = self._store( organization, current, form, profile, scenario )
        sections  = applicable_sections( profile )
        following = next_section_after( sections, current.key )
        if following is None:
            return antinode.redirect_response( reverse( 'retirement_planning' ) )
        next_profile, next_scenario = self._load( organization, following )
        next_form = following.form( profile = next_profile, scenario = next_scenario )
        return self._swap( request, sections, following, next_form )

    @staticmethod
    def _live_section( section ):
        current = section_for( section )
        if current is None or current.form is None:
            raise Http404( f'No interview section {section!r}.' )
        return current

    @staticmethod
    def _load( organization, section ):
        profile  = load_profile( latest_profile( organization ) or create_profile( organization ) )
        scenario = None
        if Aggregate.SCENARIO in section.aggregates:
            scenario = load_scenario(
                latest_scenario( organization ) or create_scenario( organization ) )
        return profile, scenario

    @staticmethod
    def _store( organization, section, form, profile, scenario ):
        new_profile, new_scenario = form.apply( profile, scenario )
        if Aggregate.PROFILE in section.aggregates:
            save_profile( organization, new_profile )
        if Aggregate.SCENARIO in section.aggregates:
            save_scenario( latest_scenario( organization ), new_scenario )
        return new_profile

    def _swap( self, request, sections, section, form ):
        context = self._context( sections, section, form )
        return antinode.response(
            main_content = render_to_string( self._SECTION_TEMPLATE, context, request = request ),
            replace_map = { self._STEPPER_TARGET: render_to_string(
                self._STEPPER_TEMPLATE, context, request = request ) },
            push_url = reverse( 'interview_section', kwargs = { 'section': section.key } ),
            scroll_to = self._SECTION_TARGET )

    def _context( self, sections, section, form ):
        return {
            'sections'        : sections,
            'current_section' : section,
            'form'            : form,
            'section_target'  : self._SECTION_TARGET,
            'stepper_target'  : self._STEPPER_TARGET,
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
