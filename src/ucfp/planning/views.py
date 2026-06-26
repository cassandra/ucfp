"""The retirement-planning hub and per-run results.

The hub (`/planning/retirement/`) orchestrates the flow without re-implementing the profile or
scenario forms: it links out to them, makes the forecast bundle explicit (which profile, which
scenario, the frame), runs it, and lists past runs. The results page (`/planning/run/<uuid>/`)
shows a captured run -- the net-worth trajectory derived from its persisted books, whether it
stopped early, and the notices.
"""
from dataclasses import replace
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
from ucfp.scenario.enums import EventKind
from ucfp.scenario.models import ScenarioRecord
from ucfp.scenario.repository import (
    create_scenario, latest_scenario, load_scenario, save_scenario, scenarios_for )

from .events import EventForm, events_context, handler_for, menu_context
from .forms import GRANULARITY, RunForm
from .interview import (
    SECTIONS, Aggregate, HomeForm, applicable_sections, next_section_after, section_for )
from .properties import RentalForm, delete_rental, rentals_context
from .spending import GroupSpendingForm, group_for_key
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
class SpendingGroupView( View ):
    """`/planning/interview/spending/<group>/` -- the inline dense editor for one spending group
    (a category, scoped to a property for Home/Rental), drilled from the §6 totals. GET expands the
    editor (or, with `collapse`, removes it); POST saves the edited amounts and refreshes the
    group's total cell, leaving the editor open."""

    _EDITOR_TEMPLATE    = 'planning/interview/sections/group_editor.html'
    _COLLAPSED_TEMPLATE = 'planning/interview/sections/group_collapsed.html'

    def get( self, request, group ):
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = render_to_string(
                self._COLLAPSED_TEMPLATE, { 'group_key': group }, request = request ) )
        profile, scenario = _current_plan( request.organization )
        form = GroupSpendingForm(
            profile = profile, scenario = scenario, group = self._group( profile, group ) )
        return self._editor_response( request, group, form )

    def post( self, request, group ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        form = GroupSpendingForm(
            request.POST, profile = profile, scenario = scenario,
            group = self._group( profile, group ) )
        if form.is_valid():
            _, updated = form.apply( profile, scenario )
            save_scenario( latest_scenario( organization ), updated )
        return self._editor_response( request, group, form )

    @staticmethod
    def _group( profile, key ):
        resolved = group_for_key( profile, key )
        if resolved is None:
            raise Http404( f'No spending group {key!r}.' )
        return resolved

    def _editor_response( self, request, group, form ):
        content = render_to_string(
            self._EDITOR_TEMPLATE, { 'group_key': group, 'form': form }, request = request )
        total = form.group_total if form.is_bound and form.is_valid() else None
        insert_map = (
            { f'spending-total-{group}': f'{total:.0f}' } if total is not None else None )
        return antinode.response( main_content = content, insert_map = insert_map )


def _current_plan( organization ):
    """The organization's current Profile and Scenario, creating either if absent."""
    profile  = load_profile( latest_profile( organization ) or create_profile( organization ) )
    scenario = load_scenario( latest_scenario( organization ) or create_scenario( organization ) )
    return profile, scenario


@method_decorator( ensure_organization, name = 'dispatch' )
class ResidenceView( View ):
    """`/planning/interview/properties/residence/` -- the residence sub-form of the §3 Properties
    pane. GET renders it; POST applies and saves just the residence (its asset, mortgage, and rent),
    then re-renders the sub-pane with the saved values."""

    _TEMPLATE = 'planning/interview/sections/residence.html'

    def get( self, request ):
        profile, scenario = _current_plan( request.organization )
        return self._response( request, HomeForm( profile = profile, scenario = scenario ) )

    def post( self, request ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        form = HomeForm( request.POST, profile = profile, scenario = scenario )
        if form.is_valid():
            profile, scenario = form.apply( profile, scenario )
            save_profile( organization, profile )
            save_scenario( latest_scenario( organization ), scenario )
            form = HomeForm( profile = profile, scenario = scenario )
        return self._response( request, form )

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'residence_form': form }, request = request ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class RentalFormView( View ):
    """`/planning/interview/properties/rentals/add/` and `.../<handle>/` -- the add/edit form for one
    rental in the §3 Properties pane. GET opens the form (blank to add, prefilled to edit, empty on
    cancel); POST validates and writes the rental as a unit, then refreshes the list and clears the
    form area."""

    _FORM_TEMPLATE = 'planning/interview/sections/rental_form.html'
    _LIST_TEMPLATE = 'planning/interview/sections/rentals_list.html'

    def get( self, request, handle = None ):
        profile, scenario = _current_plan( request.organization )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._form( request, None, None ) )
        form = RentalForm( profile = profile, scenario = scenario, handle = handle )
        return antinode.response( main_content = self._form( request, handle, form ) )

    def post( self, request, handle = None ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        form = RentalForm( request.POST, profile = profile, scenario = scenario, handle = handle )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, handle, form ) )
        profile, scenario = form.apply( profile, scenario )
        save_profile( organization, profile )
        save_scenario( latest_scenario( organization ), scenario )
        return antinode.response(
            main_content = self._form( request, None, None ),
            replace_map  = { 'rentals-list': render_to_string(
                self._LIST_TEMPLATE, { 'rentals': rentals_context( profile ) }, request = request ) } )

    def _form( self, request, handle, form ):
        return render_to_string(
            self._FORM_TEMPLATE, { 'rental_form': form, 'handle': handle }, request = request )


@method_decorator( ensure_organization, name = 'dispatch' )
class RentalDeleteView( View ):
    """`/planning/interview/properties/rentals/<handle>/delete/` -- remove a rental as a unit, then
    refresh the list."""

    _LIST_TEMPLATE = 'planning/interview/sections/rentals_list.html'

    def post( self, request, handle ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        profile, scenario = delete_rental( profile, scenario, handle )
        save_profile( organization, profile )
        save_scenario( latest_scenario( organization ), scenario )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'rentals': rentals_context( profile ) }, request = request ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class EventAddView( View ):
    """`/planning/interview/events/add/<kind>/` -- the §7 add affordance for one event kind. GET
    opens that kind's form (or, with `collapse`, returns the add menu); POST validates it, appends
    the event to the scenario, then refreshes the events list and resets the add area to the menu.
    """

    _MENU_TEMPLATE = 'planning/interview/sections/events_menu.html'
    _FORM_TEMPLATE = 'planning/interview/sections/event_form.html'
    _LIST_TEMPLATE = 'planning/interview/sections/events_list.html'

    def get( self, request, kind ):
        profile, _ = _current_plan( request.organization )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._menu( request, profile ) )
        form = EventForm( event_type = self._event_type( kind ), profile = profile )
        return antinode.response( main_content = self._form( request, kind, form ) )

    def post( self, request, kind ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        event_type = self._event_type( kind )
        form = EventForm( request.POST, event_type = event_type, profile = profile )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, kind, form ) )
        original = profile
        profile, event = event_type.provision( form.build_event(), profile )
        profile, scenario = event_type.cascade_on_add( event, profile, scenario )
        scenario = replace( scenario, events = list( scenario.events ) + [ event ] )
        if profile is not original:   # provision created an entity, or a cascade adjusted facts
            save_profile( organization, profile )
        save_scenario( latest_scenario( organization ), scenario )
        return antinode.response(
            main_content = self._menu( request, profile ),
            replace_map  = { 'events-list': self._list( request, profile, scenario ) } )

    @staticmethod
    def _event_type( kind ):
        resolved = next( ( member for member in EventKind if member.name.lower() == kind ), None )
        if resolved is None:
            raise Http404( f'No event kind {kind!r}.' )
        return handler_for( resolved )

    def _menu( self, request, profile ):
        return render_to_string(
            self._MENU_TEMPLATE, { 'menu': menu_context( profile ) }, request = request )

    def _form( self, request, kind, form ):
        return render_to_string(
            self._FORM_TEMPLATE, { 'form': form, 'kind': kind }, request = request )

    def _list( self, request, profile, scenario ):
        return render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, scenario ) },
            request = request )


@method_decorator( ensure_organization, name = 'dispatch' )
class EventDeleteView( View ):
    """`/planning/interview/events/delete/<index>/` -- remove the event at `index`, then refresh
    the events list."""

    _LIST_TEMPLATE = 'planning/interview/sections/events_list.html'

    def post( self, request, index ):
        organization = request.organization
        profile, scenario = _current_plan( organization )
        events = list( scenario.events )
        if 0 <= index < len( events ):
            original = profile
            removed  = events[ index ]
            profile, scenario = handler_for( removed.kind ).cascade_on_remove(
                removed, profile, scenario )
            del events[ index ]
            scenario = replace( scenario, events = events )
            if profile is not original:
                save_profile( organization, profile )
            save_scenario( latest_scenario( organization ), scenario )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, scenario ) },
            request = request ) )


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
