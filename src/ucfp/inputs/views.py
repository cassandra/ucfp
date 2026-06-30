"""The inputs area -- the hub plus the guided interview and its per-flow editors.

The hub (`/inputs/`) lists the current Profile and the organization's Plans and Assumptions sets,
each linking to its flow. The interview is one section machinery run as three flows (Profile, Plans,
Assumptions): `FlowEntryView` enters a single flow, `InterviewHomeView` runs all three guided, and
`InterviewView` drives one section at a time over the typed aggregates. The remaining views are the
sub-editors each section pane drills into.
"""
from dataclasses import replace

from django.http import Http404
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from common import antinode
from common.request_utils import is_ajax

from ucfp.inputs.profile.repository import (
    create_profile, latest_profile, load_profile, save_profile )
from ucfp.inputs.plans.repository import (
    create_plans, latest_plans, load_plans, plans_for, save_plans )
from ucfp.inputs.assumptions.repository import (
    assumptions_for, create_assumptions, latest_assumptions, load_assumptions, save_assumptions )
from ucfp.inputs.plans.enums import EventKind

from .interview import (
    SECTIONS, Aggregate, HomeForm, applicable_sections, first_section_of_flow, flow_of,
    flow_title, next_flow_entry, next_section_after, section_for )
from .events import EventForm, events_context, handler_for, menu_context
from .income import IncomeTableForm
from .properties import RentalForm, delete_rental, rentals_context
from .spending import GroupSpendingForm, group_for_key

_HUB_TEMPLATE = 'inputs/hub.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class InputsHubView( View ):
    """`/inputs/` -- the inputs landing. Shows the current Profile (the latest month) and the Plans
    and Assumptions sets, so the split is visible here (at selection/management time) even though the
    interview authors all three in one pass. The interview completes here."""

    def get( self, request ):
        organization = request.organization
        return render( request, _HUB_TEMPLATE, {
            'profile'     : latest_profile( organization ),
            'plans'       : plans_for( organization ),
            'assumptions' : assumptions_for( organization ),
        } )


@method_decorator( ensure_organization, name = 'dispatch' )
class InterviewHomeView( View ):
    """`/inputs/interview/` -- start the *guided* interview: run all three flows (Profile, Plans,
    Assumptions) in sequence, ending on the inputs hub. The guided flag drives the flow chaining in
    `InterviewView`."""

    def get( self, request ):
        request.session[ 'interview_guided' ] = True
        return redirect( 'interview_section', section = SECTIONS[ 0 ].key )


@method_decorator( ensure_organization, name = 'dispatch' )
class FlowEntryView( View ):
    """`/inputs/<flow>/` -- edit a single input flow (Profile, Plans, or Assumptions) on its own,
    without guided chaining: it ends on the inputs hub at the flow's last section. `flow` is set per
    route via `as_view`."""

    flow = None

    def get( self, request ):
        request.session[ 'interview_guided' ] = False
        first = first_section_of_flow( self.flow )
        if first is None:
            raise Http404( f'No sections in flow {self.flow!r}.' )
        return redirect( 'interview_section', section = first.key )


@method_decorator( ensure_organization, name = 'dispatch' )
class InterviewView( View ):
    """`/inputs/interview/<section>/` -- one section of the guided setup: an antinode-swapped
    linear flow over the organization's current Profile, Plans, and Assumptions. A full GET renders
    the whole page; an async GET (a stepper revisit) or a POST swaps just the section pane and
    refreshes the stepper.

    On a valid POST the section is saved and the *next* section is recomputed from the now-updated
    profile -- the conditional-flow payoff. Each section merges only its own part via `apply`,
    so advancing (or revisiting) never clobbers another section's facts.
    """

    _PAGE_TEMPLATE    = 'inputs/interview/page.html'
    _SECTION_TEMPLATE = 'inputs/interview/section.html'
    _STEPPER_TEMPLATE = 'inputs/interview/stepper.html'
    _SECTION_TARGET   = 'interview-section'
    _STEPPER_TARGET   = 'interview-stepper'

    def get( self, request, section ):
        current  = self._live_section( section )
        profile, other = self._load( request.organization, current )
        sections = self._flow_sections( profile, flow_of( current ) )
        form     = self._form( current, profile, other )
        if is_ajax( request ):
            return self._swap( request, sections, current, form )
        return render( request, self._PAGE_TEMPLATE, self._context( sections, current, form ) )

    def post( self, request, section ):
        current = self._live_section( section )
        organization = request.organization
        flow = flow_of( current )
        profile, other = self._load( organization, current )
        form = self._form( current, profile, other, request.POST )
        if not form.is_valid():
            return self._swap( request, self._flow_sections( profile, flow ), current, form )
        profile   = self._store( organization, current, form, profile, other )
        following = next_section_after( self._flow_sections( profile, flow ), current.key )
        if following is None and request.session.get( 'interview_guided' ):
            following = next_flow_entry( flow )         # guided: advance into the next flow
        if following is None:
            return antinode.redirect_response( reverse( 'inputs_home' ) )
        next_sections = self._flow_sections( profile, flow_of( following ) )
        next_profile, next_other = self._load( organization, following )
        next_form = self._form( following, next_profile, next_other )
        return self._swap( request, next_sections, following, next_form )

    @staticmethod
    def _flow_sections( profile, flow ):
        """The applicable sections of one flow -- the stepper's scope, so each flow shows only its
        own steps."""
        return [ section for section in applicable_sections( profile ) if flow_of( section ) == flow ]

    @staticmethod
    def _live_section( section ):
        current = section_for( section )
        if current is None or current.form is None:
            raise Http404( f'No interview section {section!r}.' )
        return current

    @classmethod
    def _form( cls, section, profile, other, data = None ):
        """Build the section's form, passing its non-profile aggregate under the keyword that form
        expects: `assumptions` for the external-factors section, `plans` for the rest."""
        keyword = 'assumptions' if Aggregate.ASSUMPTIONS in section.aggregates else 'plans'
        return section.form( data, profile = profile, **{ keyword: other } )

    @staticmethod
    def _load( organization, section ):
        """The profile, plus the one non-profile aggregate this section edits (a Plans, an
        Assumptions, or neither) -- creating the record if absent so the form has something to bind.
        No section edits both Plans and Assumptions, so a single `other` suffices."""
        assert not ( Aggregate.PLANS in section.aggregates
                     and Aggregate.ASSUMPTIONS in section.aggregates ), (
            f'Section {section.key!r} edits both Plans and Assumptions; the single-other dispatch '
            'supports at most one non-profile aggregate per section.' )
        profile = load_profile( latest_profile( organization ) or create_profile( organization ) )
        if Aggregate.PLANS in section.aggregates:
            return profile, load_plans( latest_plans( organization ) or create_plans( organization ) )
        if Aggregate.ASSUMPTIONS in section.aggregates:
            return profile, load_assumptions(
                latest_assumptions( organization ) or create_assumptions( organization ) )
        return profile, None

    @staticmethod
    def _store( organization, section, form, profile, other ):
        new_profile, new_other = form.apply( profile, other )
        if Aggregate.PROFILE in section.aggregates:
            save_profile( organization, new_profile )
        if Aggregate.PLANS in section.aggregates:
            save_plans( latest_plans( organization ), new_other )
        elif Aggregate.ASSUMPTIONS in section.aggregates:
            save_assumptions( latest_assumptions( organization ), new_other )
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
            'flow_title'      : flow_title( flow_of( section ) ),
            'form'            : form,
            'section_target'  : self._SECTION_TARGET,
            'stepper_target'  : self._STEPPER_TARGET,
        }


@method_decorator( ensure_organization, name = 'dispatch' )
class SpendingGroupView( View ):
    """`/inputs/interview/spending/<group>/` -- the inline dense editor for one spending group
    (a category, scoped to a property for Home/Rental), drilled from the §6 totals. GET expands the
    editor (or, with `collapse`, removes it); POST saves the edited amounts and refreshes the
    group's total cell, leaving the editor open."""

    _EDITOR_TEMPLATE    = 'inputs/interview/sections/group_editor.html'
    _COLLAPSED_TEMPLATE = 'inputs/interview/sections/group_collapsed.html'

    def get( self, request, group ):
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = render_to_string(
                self._COLLAPSED_TEMPLATE, { 'group_key': group }, request = request ) )
        profile, plans = _current_profile_and_plans( request.organization )
        form = GroupSpendingForm(
            profile = profile, plans = plans, group = self._group( profile, group ) )
        return self._editor_response( request, group, form )

    def post( self, request, group ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        form = GroupSpendingForm(
            request.POST, profile = profile, plans = plans,
            group = self._group( profile, group ) )
        if form.is_valid():
            _, updated = form.apply( profile, plans )
            save_plans( latest_plans( organization ), updated )
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
            { f'spending-total-{group}': request.organization.currency.format( total ) }
            if total is not None else None )
        return antinode.response( main_content = content, insert_map = insert_map )


def _current_profile_and_plans( organization ):
    """The organization's current Profile and Plans, creating either if absent."""
    profile  = load_profile( latest_profile( organization ) or create_profile( organization ) )
    plans = load_plans( latest_plans( organization ) or create_plans( organization ) )
    return profile, plans


@method_decorator( ensure_organization, name = 'dispatch' )
class ResidenceView( View ):
    """`/inputs/interview/properties/residence/` -- the residence sub-form of the §3 Properties
    pane. GET renders it; POST applies and saves just the residence (its asset, mortgage, and rent),
    then re-renders the sub-pane with the saved values."""

    _TEMPLATE = 'inputs/interview/sections/residence.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request.organization )
        return self._response( request, HomeForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        form = HomeForm( request.POST, profile = profile, plans = plans )
        if form.is_valid():
            profile, plans = form.apply( profile, plans )
            save_profile( organization, profile )
            save_plans( latest_plans( organization ), plans )
            form = HomeForm( profile = profile, plans = plans )
        return self._response( request, form )

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'residence_form': form }, request = request ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class IncomeTableView( View ):
    """`/inputs/interview/income/table/` -- the §5 income table. GET renders it. POST auto-saves a
    single edit in the background: it persists, then replies *silently* (an empty antinode response,
    no DOM swap) for a pure value edit so typing flow is undisturbed, and re-renders the pane only
    when the row set changed (a line added or removed) or a field failed validation -- cases the
    client cannot reflect on its own. The age<->date sync is done client-side (`income_table.js`)."""

    _TEMPLATE = 'inputs/interview/sections/income_table.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request.organization )
        return self._rendered( request, IncomeTableForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        form = IncomeTableForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # show field errors
        before = self._line_count( profile )
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( latest_plans( organization ), plans )
        if self._line_count( profile ) != before:              # a line was added or removed
            return self._swap( request, IncomeTableForm( profile = profile, plans = plans ) )
        return antinode.response()                             # silent: nothing to re-render

    @staticmethod
    def _line_count( profile ) -> int:
        """The general income lines (the only rows whose count changes); rental and entitlement rows
        are fixed by the properties and subjects."""
        return sum( 1 for flow in profile.income_flows if flow.property_handle is None )

    def _rendered( self, request, form ) -> str:
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'income_form': form }, request = request ) )

    def _swap( self, request, form ):
        # Replace the pane by id (not the data-async target) so the loader-suppressed background
        # POST -- which carries no target -- still applies the update.
        return antinode.response( replace_map = { 'income-table': render_to_string(
            self._TEMPLATE, { 'income_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class RentalFormView( View ):
    """`/inputs/interview/properties/rentals/add/` and `.../<handle>/` -- the add/edit form for one
    rental in the §3 Properties pane. GET opens the form (blank to add, prefilled to edit, empty on
    cancel); POST validates and writes the rental as a unit, then refreshes the list and clears the
    form area."""

    _FORM_TEMPLATE = 'inputs/interview/sections/rental_form.html'
    _LIST_TEMPLATE = 'inputs/interview/sections/rentals_list.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request.organization )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._form( request, None, None ) )
        form = RentalForm( profile = profile, plans = plans, handle = handle )
        return antinode.response( main_content = self._form( request, handle, form ) )

    def post( self, request, handle = None ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        form = RentalForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, handle, form ) )
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( latest_plans( organization ), plans )
        return antinode.response(
            main_content = self._form( request, None, None ),
            replace_map  = { 'rentals-list': render_to_string(
                self._LIST_TEMPLATE, { 'rentals': rentals_context( profile ) }, request = request ) } )

    def _form( self, request, handle, form ):
        return render_to_string(
            self._FORM_TEMPLATE, { 'rental_form': form, 'handle': handle }, request = request )


@method_decorator( ensure_organization, name = 'dispatch' )
class RentalDeleteView( View ):
    """`/inputs/interview/properties/rentals/<handle>/delete/` -- remove a rental as a unit, then
    refresh the list."""

    _LIST_TEMPLATE = 'inputs/interview/sections/rentals_list.html'

    def post( self, request, handle ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        profile, plans = delete_rental( profile, plans, handle )
        save_profile( organization, profile )
        save_plans( latest_plans( organization ), plans )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'rentals': rentals_context( profile ) }, request = request ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class EventAddView( View ):
    """`/inputs/interview/events/add/<kind>/` -- the §7 add affordance for one event kind. GET
    opens that kind's form (or, with `collapse`, returns the add menu); POST validates it, appends
    the event to the plans, then refreshes the events list and resets the add area to the menu.
    """

    _MENU_TEMPLATE = 'inputs/interview/sections/events_menu.html'
    _FORM_TEMPLATE = 'inputs/interview/sections/event_form.html'
    _LIST_TEMPLATE = 'inputs/interview/sections/events_list.html'

    def get( self, request, kind ):
        profile, _ = _current_profile_and_plans( request.organization )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._menu( request, profile ) )
        form = EventForm( event_type = self._event_type( kind ), profile = profile )
        return antinode.response( main_content = self._form( request, kind, form ) )

    def post( self, request, kind ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        event_type = self._event_type( kind )
        form = EventForm( request.POST, event_type = event_type, profile = profile )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, kind, form ) )
        original = profile
        profile, event = event_type.provision( form.build_event(), profile )
        profile, plans = event_type.cascade_on_add( event, profile, plans )
        plans = replace( plans, events = list( plans.events ) + [ event ] )
        if profile is not original:   # provision created an entity, or a cascade adjusted facts
            save_profile( organization, profile )
        save_plans( latest_plans( organization ), plans )
        return antinode.response(
            main_content = self._menu( request, profile ),
            replace_map  = { 'events-list': self._list( request, profile, plans ) } )

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

    def _list( self, request, profile, plans ):
        return render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) },
            request = request )


@method_decorator( ensure_organization, name = 'dispatch' )
class EventDeleteView( View ):
    """`/inputs/interview/events/delete/<index>/` -- remove the event at `index`, then refresh
    the events list."""

    _LIST_TEMPLATE = 'inputs/interview/sections/events_list.html'

    def post( self, request, index ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( organization )
        events = list( plans.events )
        if 0 <= index < len( events ):
            original = profile
            removed  = events[ index ]
            profile, plans = handler_for( removed.kind ).cascade_on_remove(
                removed, profile, plans )
            del events[ index ]
            plans = replace( plans, events = events )
            if profile is not original:
                save_profile( organization, profile )
            save_plans( latest_plans( organization ), plans )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) },
            request = request ) )
