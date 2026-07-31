"""The inputs area -- the Scenarios landing plus the guided interview and its per-flow editors.

The Scenarios landing (`/inputs/scenarios/`) lists the organization's scenarios and hosts the Plans and
Assumptions management; the Profile is edited on its own flow (reached from the nav). The interview is
one section machinery run as three flows (Profile, Plans, Assumptions): `FlowEntryView` enters a single
flow and `InterviewView` drives one section at a time over the typed aggregates. Profile is the
standalone first setup; the Plans/Assumptions flows compose into a scenario (the build flow chains them).
The remaining views are the sub-editors each section pane drills into.
"""
from dataclasses import replace

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
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
    clone_plans, create_plans, delete_plans, latest_plans, load_plans, plans_for, rename_plans,
    save_plans )
from ucfp.inputs.assumptions.repository import (
    assumptions_for, clone_assumptions, create_assumptions, delete_assumptions, latest_assumptions,
    load_assumptions, rename_assumptions, save_assumptions )
from ucfp.inputs.scenarios.repository import scenarios_for, start_scenario
from ucfp.inputs.plans.enums import EventKind

from .interview import (
    Aggregate, AccountsForm, HomeForm, SubjectsForm, applicable_sections,
    first_section_of_flow, flow_of, flow_title, next_section_after, section_for )
from .models import AssumptionsRecord, PlansRecord, ScenarioRecord
from .vehicle import VehicleForm, delete_vehicle, vehicles_context, _minted_vehicle_handle
from .vehicle_expenses import VehicleExpensesForm
from .credit_card import CreditCardPlanForm
from .external_factors import ExternalFactorsForm
from .cash_plan import DrawdownForm
from .transaction_costs import TransactionCostsForm
from .debt_plan import DebtPlanForm
from .debts import DebtsForm
from .events import EventForm, events_context, handler_for, menu_context
from .income import IncomeTableForm
from .properties import (
    RENTAL_PANE, SECOND_HOME_PANE, PossessionsForm, PropertyPane, _minted_handle, delete_property,
    properties_context )
from .property_expenses import PropertyExpensesForm
from .recurring_expenses import RecurringExpensesForm

_SCENARIOS_TEMPLATE = 'inputs/scenarios_home.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenariosHomeView( View ):
    """`/inputs/scenarios/` -- the Scenarios landing: the organization's saved scenarios, plus the Plans
    and Assumptions management (a scenario is a combination of those, so its components are managed here).
    A placeholder for now -- scenario building and per-scenario management arrive later; this only lists
    them and keeps the component editors reachable. Perspective-agnostic: it links to the component
    editors but to no planning perspective (forecast, retirement, ...) -- the main nav reaches those."""

    def get( self, request ):
        organization = request.organization
        # `select_related` the components (the list shows each scenario's Plans/Assumptions labels), and
        # prefetch each set's referencing scenarios so a delete confirmation can warn which scenarios it
        # would cascade away (a scenario references its Plans/Assumptions).
        return render( request, _SCENARIOS_TEMPLATE, {
            'active_nav'  : 'scenarios',
            'scenarios'   : scenarios_for( organization ).select_related( 'plans', 'assumptions' ),
            'plans'       : plans_for( organization ).prefetch_related( 'scenarios' ),
            'assumptions' : assumptions_for( organization ).prefetch_related( 'scenarios' ),
        } )


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioBuildStartView( View ):
    """`/inputs/scenarios/build/` -- begin building a new Future Scenario. GET explains what a scenario is
    (forward-looking, unlike the Profile's facts) and takes a name; POST mints the scenario with its own
    Plans and Assumptions (named after it), makes them the editing target, marks the build in progress,
    and opens the two-part flow at the first Plans section. A Profile is the prerequisite -- without one
    the user is sent to build it first and returned here."""

    _TEMPLATE = 'inputs/scenario_build_start.html'

    def get( self, request ):
        if latest_profile( request.organization ) is None:
            return self._require_profile( request )
        return render( request, self._TEMPLATE, {} )

    def post( self, request ):
        organization = request.organization
        if latest_profile( organization ) is None:
            return self._require_profile( request )
        name     = ( request.POST.get( 'name' ) or '' ).strip() or 'Future Scenario'
        scenario = start_scenario( organization, name )
        _select( request, 'current_plans_uuid', scenario.plans )
        _select( request, 'current_assumptions_uuid', scenario.assumptions )
        request.session_state.scenario_building = str( scenario.uuid )
        request.session_state.to_session( request )
        return redirect( 'interview_section', section = first_section_of_flow( 'plans' ).key )

    @staticmethod
    def _require_profile( request ):
        """No Profile yet: it is the universal prerequisite, so route to it and return here once done."""
        request.session_state.post_setup_return = reverse( 'scenario_build' )
        request.session_state.to_session( request )
        return redirect( 'flow_profile' )


@method_decorator( ensure_organization, name = 'dispatch' )
class FlowEntryView( View ):
    """`/inputs/<flow>/` -- edit a single input flow (Profile, Plans, or Assumptions) on its own. `flow`
    is set per route via `as_view`. Profile is the standalone first flow; Plans/Assumptions are edited on
    their own here (and, in the scenario-building flow, chained -- see `InterviewView`)."""

    flow = None

    def get( self, request ):
        first = first_section_of_flow( self.flow )
        if first is None:
            raise Http404( f'No sections in flow {self.flow!r}.' )
        return redirect( 'interview_section', section = first.key )


def _consume_post_setup_return( request ) -> str:
    """Where to send the user now that deflected setup has completed: the path a feature stashed when it
    sent them here, popped so it fires once, else the home page. The counterpart to the gate that sets
    `post_setup_return`."""
    destination = request.session_state.post_setup_return
    if destination:
        request.session_state.post_setup_return = None
        request.session_state.to_session( request )
        return destination
    return reverse( 'home' )


def _select( request, field, record ):
    """Make `record` the current editing target for its aggregate (by session `field`), so the flow
    edits it. The single place a plans/assumptions selection is recorded."""
    setattr( request.session_state, field, str( record.uuid ) )
    request.session_state.to_session( request )


def _forget_if_current( request, field, record ):
    """Clear the session editing target for its aggregate if it points at `record` -- called before a
    delete, so a stale selection does not outlive the record (the resolver then falls back to latest)."""
    if getattr( request.session_state, field ) == str( record.uuid ):
        setattr( request.session_state, field, None )
        request.session_state.to_session( request )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansNewView( View ):
    """`/inputs/plans/new/` -- mint a new Plans set, make it the current editing target, and open the
    plans flow on it. POST, since it creates a record."""

    def post( self, request ):
        _select( request, 'current_plans_uuid', create_plans( request.organization ) )
        return redirect( 'flow_plans' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansSelectView( View ):
    """`/inputs/plans/<uuid>/` -- make an existing Plans set the current editing target and open the
    plans flow on it."""

    def get( self, request, uuid ):
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_plans_uuid', record )
        return redirect( 'flow_plans' )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsNewView( View ):
    """`/inputs/assumptions/new/` -- mint a new Assumptions set, make it the current editing target,
    and open the assumptions flow on it. POST, since it creates a record."""

    def post( self, request ):
        _select( request, 'current_assumptions_uuid', create_assumptions( request.organization ) )
        return redirect( 'flow_assumptions' )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsSelectView( View ):
    """`/inputs/assumptions/<uuid>/` -- make an existing Assumptions set the current editing target
    and open the assumptions flow on it."""

    def get( self, request, uuid ):
        record = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_assumptions_uuid', record )
        return redirect( 'flow_assumptions' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansRenameView( View ):
    """`/inputs/plans/<uuid>/rename/` -- rename a Plans set from the hub's inline editor. Saves the new
    label in the background and replies silently; a blank name is ignored (non-blocking)."""

    def post( self, request, uuid ):
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        label  = request.POST.get( 'label', '' ).strip()
        if label:
            rename_plans( record, label )
        return antinode.response()


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsRenameView( View ):
    """`/inputs/assumptions/<uuid>/rename/` -- rename an assumptions set from the hub's inline editor.
    Saves the new label in the background and replies silently; a blank name is ignored."""

    def post( self, request, uuid ):
        record = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        label  = request.POST.get( 'label', '' ).strip()
        if label:
            rename_assumptions( record, label )
        return antinode.response()


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansCloneView( View ):
    """`/inputs/plans/<uuid>/clone/` -- duplicate a Plans set (its contents plus a "copy" name), make
    the copy the current editing target, and open it for tweaking. POST, since it creates a record."""

    def post( self, request, uuid ):
        source = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_plans_uuid', clone_plans( source ) )
        return redirect( 'flow_plans' )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsCloneView( View ):
    """`/inputs/assumptions/<uuid>/clone/` -- duplicate an Assumptions set (its contents plus a "copy"
    name), make the copy the current editing target, and open it for tweaking. POST, since it creates
    a record."""

    def post( self, request, uuid ):
        source = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_assumptions_uuid', clone_assumptions( source ) )
        return redirect( 'flow_assumptions' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansDeleteView( View ):
    """`/inputs/plans/<uuid>/delete/` -- delete a Plans set (destructive; the hub asks first). If it
    was the current editing target, the selection is cleared so the next visit falls back to the
    latest (or a fresh) set."""

    def post( self, request, uuid ):
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _forget_if_current( request, 'current_plans_uuid', record )
        delete_plans( record )
        return redirect( 'scenarios_home' )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsDeleteView( View ):
    """`/inputs/assumptions/<uuid>/delete/` -- delete an assumptions set (destructive; the hub asks
    first). If it was the current editing target, the selection is cleared so the next visit falls
    back to the latest (or a fresh) set."""

    def post( self, request, uuid ):
        record = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        _forget_if_current( request, 'current_assumptions_uuid', record )
        delete_assumptions( record )
        return redirect( 'scenarios_home' )


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
        self._seed_and_acknowledge( request, current )         # presenting the section is the acknowledgment
        profile, other = self._load( request, current )
        sections = self._flow_sections( profile, flow_of( current ) )
        form     = self._form( current, profile, other )
        if is_ajax( request ):
            return self._swap( request, sections, current, form )
        return render( request, self._PAGE_TEMPLATE, self._context( request, sections, current, form ) )

    def _seed_and_acknowledge( self, request, section ):
        """Presenting a section to the user is the acknowledgment that they have seen it. On the first
        view a *seeding* section (one whose `apply` is a pure catalog merge) also persists its defaults,
        so what the user sees is already saved (matching the auto-save spirit) and an acknowledged spending
        section is never empty. Both happen only here -- the merge builders are never a source of
        acknowledgment on their own -- and only on first view, so revisits are inert."""
        record = self._flow_record( request, flow_of( section ) )
        if section.key in record.acknowledged_section_keys:
            return
        if getattr( section.form, 'seeds_on_render', False ):
            profile, other = self._load( request, section )
            self._store( request, section, self._form( section, profile, other ), profile, other )
        record.acknowledge( section.key )

    @staticmethod
    def _flow_record( request, flow ):
        """The current record a `flow` edits -- the single flow -> record dispatch, used for a section's
        acknowledgment, the stepper's seen marks, and the flow heading. The run gate later unions the
        current bundle's three records, so which record holds a given section key does not matter (a
        section can move between flows)."""
        if flow == 'plans':
            return current_plans_record( request )
        if flow == 'assumptions':
            return current_assumptions_record( request )
        return latest_profile( request.organization ) or create_profile( request.organization )

    def post( self, request, section ):
        current = self._live_section( section )
        flow = flow_of( current )
        profile, other = self._load( request, current )
        form = self._form( current, profile, other, request.POST )
        if not form.is_valid():
            return self._swap( request, self._flow_sections( profile, flow ), current, form )
        profile   = self._store( request, current, form, profile, other )
        following = next_section_after( self._flow_sections( profile, flow ), current.key )
        building  = request.session_state.scenario_building
        if following is None and building and flow == 'plans':
            following = first_section_of_flow( 'assumptions' )  # scenario build: chain Plans -> Assumptions
        if following is None:                                   # nothing more to present -- this flow ends
            return antinode.redirect_response( self._completion_destination( request, flow, building ) )
        self._seed_and_acknowledge( request, following )       # the advanced-to section is now presented
        next_sections = self._flow_sections( profile, flow_of( following ) )
        next_profile, next_other = self._load( request, following )
        next_form = self._form( following, next_profile, next_other )
        return self._swap( request, next_sections, following, next_form )

    @staticmethod
    def _completion_destination( request, flow, building ) -> str:
        """Where a completed flow lands. A scenario build (Plans then Assumptions) finishes at the end of
        Assumptions: clear the in-progress marker and return the user wherever a feature deflected them
        (else home). A standalone Profile likewise returns whence deflected; a standalone component edit
        ends on the Scenarios landing."""
        if building:                                           # end of the two-part build (Assumptions done)
            request.session_state.scenario_building = None
            request.session_state.to_session( request )
            return _consume_post_setup_return( request )
        if flow == 'profile':
            return _consume_post_setup_return( request )
        return reverse( 'scenarios_home' )

    @staticmethod
    def _building_scenario_name( request ):
        """The label of the scenario currently being built, or None when no build is in progress -- the
        breadcrumb context for the two-part build flow."""
        uuid = request.session_state.scenario_building
        if uuid is None:
            return None
        record = ScenarioRecord.objects.filter(
            uuid = uuid, organization = request.organization ).first()
        return record.label if record is not None else None

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
    def _load( request, section ):
        """The profile, plus the one non-profile aggregate this section edits (a Plans, an
        Assumptions, or neither) -- the session-selected record, creating it if absent so the form has
        something to bind. No section edits both Plans and Assumptions, so a single `other` suffices."""
        assert not ( Aggregate.PLANS in section.aggregates
                     and Aggregate.ASSUMPTIONS in section.aggregates ), (
            f'Section {section.key!r} edits both Plans and Assumptions; the single-other dispatch '
            'supports at most one non-profile aggregate per section.' )
        organization = request.organization
        profile = load_profile( latest_profile( organization ) or create_profile( organization ) )
        if Aggregate.PLANS in section.aggregates:
            return profile, load_plans( current_plans_record( request ) )
        if Aggregate.ASSUMPTIONS in section.aggregates:
            return profile, load_assumptions( current_assumptions_record( request ) )
        return profile, None

    @staticmethod
    def _store( request, section, form, profile, other ):
        new_profile, new_other = form.apply( profile, other )
        with transaction.atomic():                             # a straddle section writes both; keep them in step
            if Aggregate.PROFILE in section.aggregates:
                save_profile( request.organization, new_profile )
            if Aggregate.PLANS in section.aggregates:
                save_plans( current_plans_record( request ), new_other )
            elif Aggregate.ASSUMPTIONS in section.aggregates:
                save_assumptions( current_assumptions_record( request ), new_other )
        return new_profile

    def _swap( self, request, sections, section, form ):
        context = self._context( request, sections, section, form )
        return antinode.response(
            main_content = render_to_string( self._SECTION_TEMPLATE, context, request = request ),
            replace_map = { self._STEPPER_TARGET: render_to_string(
                self._STEPPER_TEMPLATE, context, request = request ) },
            push_url = reverse( 'interview_section', kwargs = { 'section': section.key } ),
            scroll_to = self._SECTION_TARGET )

    def _context( self, request, sections, section, form ):
        flow = flow_of( section )
        return {
            'sections'             : sections,
            'current_section'      : section,
            # The current flow's record only -- the stepper shows one flow's steps, so its seen marks are
            # flow-scoped (the run gate, spanning all three records, is the cross-flow view).
            'acknowledged_sections': self._flow_record( request, flow ).acknowledged_section_keys,
            'flow'                 : flow,
            # Which top-level nav home this flow belongs under, so it stays lit while editing (the flow
            # editors all resolve to `interview_section`, so nav-active can't key on the url name). Profile
            # is its own home; Plans and Assumptions are scenario components, under Scenarios.
            'active_nav'           : 'profile' if flow == 'profile' else 'scenarios',
            'flow_title'           : flow_title( flow ),
            'flow_heading'         : self._flow_heading( request, flow ),
            # The scenario being built (its name), so the component flows breadcrumb it during a build.
            'building_scenario'    : self._building_scenario_name( request ),
            'form'                 : form,
            'section_target'       : self._SECTION_TARGET,
            'stepper_target'       : self._STEPPER_TARGET,
        }

    def _flow_heading( self, request, flow ) -> str:
        """The flow's title with the record being edited named, for the page heading -- "Plans: Base
        case", "Assumptions: Optimistic" -- so the user sees which of several they are editing. The
        single-record Profile shows just its title."""
        title = flow_title( flow )
        if flow in ( 'plans', 'assumptions' ):
            return f'{title}: {self._flow_record( request, flow ).label}'
        return title


@method_decorator( ensure_organization, name = 'dispatch' )
class SelfSavingPaneView( View ):
    """Shared shape for a self-saving input pane: GET renders the pane; POST validates the edit and
    re-renders the pane only on a genuine field error, otherwise persisting it silently so typing is
    undisturbed. A pane whose row set can change re-renders after a save that added or removed a row.

    A concrete pane declares its `template`, the pane's DOM `target` id, and the `context_name` the
    template reads its form under, and implements `build_form` (construct the form from the current
    aggregates) and `persist` (apply the valid form and save). `persist` returns truthy only when the
    row set changed, so the pane is re-rendered; a plain value edit returns None and stays silent.
    Non-blocking throughout -- an incomplete entry simply is not saved; the forecast readiness check
    is the completeness gate. Panes with a non-silent success (Subjects) do not use this base."""

    template     : str
    target       : str
    context_name : str

    def get( self, request ):
        return antinode.response( main_content = self._pane( request, self.build_form( request ) ) )

    def post( self, request ):
        form = self.build_form( request, request.POST )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        if self.persist( request, form ):                      # a row was added or removed
            return self._swap( request, self.build_form( request ) )
        return antinode.response()                             # silent background save

    def build_form( self, request, data = None ):
        raise NotImplementedError

    def persist( self, request, form ):
        raise NotImplementedError

    def _pane( self, request, form ) -> str:
        return render_to_string( self.template, { self.context_name: form }, request = request )

    def _swap( self, request, form ):
        # Replace the pane by id (not a data-async target) so the loader-suppressed background POST,
        # which carries no target, still applies the re-render.
        return antinode.response( replace_map = { self.target: self._pane( request, form ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class _VehicleListView( View ):
    """Shared, org-scoped base for the vehicle list of the Vehicle Expenses step: it renders the plan's
    vehicles. The per-vehicle add/edit/delete swaps refresh this list; the per-car running costs are the
    sibling `VehicleExpensesView` pane."""

    _LIST_TEMPLATE = 'inputs/interview/sections/vehicle_list.html'

    def _list( self, request, plans ):
        return render_to_string(
            self._LIST_TEMPLATE, { 'vehicles': vehicles_context( plans ) }, request = request )


class VehicleFormView( _VehicleListView ):
    """`/inputs/interview/vehicle-expenses/vehicles/add/` and `.../<handle>/` -- the add/edit form for
    one vehicle. Add and edit converge on a minted handle, so a new vehicle has a stable identity from
    the first keystroke. POST background-saves (non-blocking, so an incomplete vehicle writes nothing)
    and refreshes the list; the open form is left untouched except to surface a genuine field error."""

    _FORM_TEMPLATE = 'inputs/interview/sections/vehicle_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._form( request, None, None ) )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_vehicle_handle( plans )
        form = VehicleForm( profile = profile, plans = plans, handle = handle )
        return antinode.response( main_content = self._form( request, handle, form ) )

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = VehicleForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'vehicles-form': self._form( request, handle, form ) } )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response( replace_map = { 'vehicles-list': self._list( request, plans ) } )

    def _form( self, request, handle, form ):
        return render_to_string(
            self._FORM_TEMPLATE, { 'vehicle_form': form, 'handle': handle }, request = request )


class VehicleDeleteView( _VehicleListView ):
    """`.../vehicle-expenses/vehicles/<handle>/delete/` -- remove one vehicle, then refresh the list."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        plans = delete_vehicle( plans, handle )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response( replace_map = { 'vehicles-list': self._list( request, plans ) } )


class RecurringExpensesView( SelfSavingPaneView ):
    """`/inputs/interview/living-expenses/edit/` -- the recurring-expenses table of the Living Expenses
    step: the `LIVING`-class expenses over the shared age-span timeline. Auto-saves each edit; a
    structural change (a span added, removed, or re-aged) re-renders the table, a pure amount edit
    stays silent."""

    template     = 'inputs/interview/sections/recurring_expenses.html'
    target       = 'recurring-expenses'
    context_name = 'recurring_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return RecurringExpensesForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        changed = form.spans_changed()
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )
        return changed                                     # a span changed -> re-render the table


class PropertyExpensesView( SelfSavingPaneView ):
    """`/inputs/interview/home-expenses/edit/` -- the property-expenses matrix of the Home Expenses
    step: the household's per-property operating costs as one shared default with per-property overrides.
    Auto-saves each edit silently; the row and column sets change only when a property is added or
    removed (in the Property section), so this pane never restructures itself."""

    template     = 'inputs/interview/sections/property_expenses.html'
    target       = 'property-expenses'
    context_name = 'property_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return PropertyExpensesForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


class VehicleExpensesView( SelfSavingPaneView ):
    """`/inputs/interview/vehicle-expenses/costs/edit/` -- the per-car running-costs table of the
    Vehicle Expenses step. Auto-saves each edit onto the vehicle plan's running costs; the row set is
    fixed (the catalog's vehicle costs), so it saves silently and never restructures."""

    template     = 'inputs/interview/sections/_vehicle_expenses.html'
    target       = 'vehicle-running-costs'
    context_name = 'vehicle_costs_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return VehicleExpensesForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


def current_plans_record( request ):
    """The Plans record the user is editing: the session-selected one (scoped to the org), else the
    latest, minting one if the org has none. The single resolver every plans surface loads and saves
    through, so a selection made on the hub drives the whole flow."""
    organization = request.organization
    uuid = request.session_state.current_plans_uuid
    if uuid is not None:
        selected = plans_for( organization ).filter( uuid = uuid ).first()
        if selected is not None:
            return selected
    return latest_plans( organization ) or create_plans( organization )


def current_assumptions_record( request ):
    """The Assumptions record the user is editing -- the session-selected one (scoped to the org),
    else the latest, minting one if the org has none."""
    organization = request.organization
    uuid = request.session_state.current_assumptions_uuid
    if uuid is not None:
        selected = assumptions_for( organization ).filter( uuid = uuid ).first()
        if selected is not None:
            return selected
    return latest_assumptions( organization ) or create_assumptions( organization )


def _current_profile( request ):
    """The user's current Profile -- the latest month's, creating one if the org has none yet."""
    organization = request.organization
    return load_profile( latest_profile( organization ) or create_profile( organization ) )


def _current_profile_and_plans( request ):
    """The user's current Profile and the contents of the Plans record they are editing, creating
    either if absent."""
    return _current_profile( request ), load_plans( current_plans_record( request ) )


def _save_profile_and_plans( request, profile, plans ):
    """Persist a paired profile+plans edit atomically -- both commit together or neither does, so a
    failed second write cannot leave the Profile and Plans out of step (the very drift the
    `compatibility` module guards against). The single seam the paired-save panes write through."""
    with transaction.atomic():
        save_profile( request.organization, profile )
        save_plans( current_plans_record( request ), plans )


def _current_assumptions( request ):
    """The contents of the Assumptions record the user is editing, creating it if absent."""
    return load_assumptions( current_assumptions_record( request ) )


class ResidenceView( SelfSavingPaneView ):
    """`/inputs/interview/properties/residence/` -- the residence sub-form of the Property pane. It
    persists just the residence (its asset, mortgage, and rent). Own/rent and mortgage visibility are
    client-side (`inputs.js`); an incomplete residence simply does not materialize."""

    template     = 'inputs/interview/sections/residence.html'
    target       = 'residence'
    context_name = 'residence_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return HomeForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )


class ExternalFactorsView( SelfSavingPaneView ):
    """`/inputs/interview/external-factors/edit/` -- the External Factors pane of the Assumptions
    flow. It persists the assumptions' economic factors and tax projection."""

    template     = 'inputs/interview/sections/external_factors_pane.html'
    target       = 'external-factors'
    context_name = 'factors_form'

    def build_form( self, request, data = None ):
        return ExternalFactorsForm( data, assumptions = _current_assumptions( request ) )

    def persist( self, request, form ):
        _profile, assumptions = form.apply( None, _current_assumptions( request ) )
        save_assumptions( current_assumptions_record( request ), assumptions )


class TransactionCostsView( SelfSavingPaneView ):
    """`/inputs/interview/transaction-costs/edit/` -- the Selling Costs pane of the Assumptions flow. It
    persists the transaction-cost assumptions applied when an asset is sold."""

    template     = 'inputs/interview/sections/transaction_costs_pane.html'
    target       = 'transaction-costs'
    context_name = 'costs_form'

    def build_form( self, request, data = None ):
        return TransactionCostsForm( data, assumptions = _current_assumptions( request ) )

    def persist( self, request, form ):
        _profile, assumptions = form.apply( None, _current_assumptions( request ) )
        save_assumptions( current_assumptions_record( request ), assumptions )


class CashPlanView( SelfSavingPaneView ):
    """`/inputs/interview/cash-plan/edit/` -- the Cash Plan pane of the Plans flow. It persists the
    cash band and the draw-order priority; the sweep allocation is a later section."""

    template     = 'inputs/interview/sections/cash_plan_pane.html'
    target       = 'cash-plan'
    context_name = 'drawdown_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return DrawdownForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


class AccountsView( SelfSavingPaneView ):
    """`/inputs/interview/accounts/edit/` -- the Accounts pane of the Profile flow. It persists the
    household's account balances; a blank account is simply not held."""

    template     = 'inputs/interview/sections/accounts_pane.html'
    target       = 'accounts'
    context_name = 'accounts_form'

    def build_form( self, request, data = None ):
        profile, _plans = _current_profile_and_plans( request )
        return AccountsForm( data, profile = profile )

    def persist( self, request, form ):
        profile, _plans = _current_profile_and_plans( request )
        profile, _ = form.apply( profile, None )
        save_profile( request.organization, profile )


@method_decorator( ensure_organization, name = 'dispatch' )
class SubjectsView( View ):
    """`/inputs/interview/subjects/edit/` -- the Subjects pane of the Profile flow. POST auto-saves a
    single edit in the background: it persists the household (and the derived filing status) and
    refreshes the read-only filing-status readout beside the form, re-rendering the pane itself only on
    a genuine field error (a half-entered partner). Validation is non-blocking -- an incomplete person
    is simply not held; the forecast readiness check is the completeness gate."""

    _TEMPLATE        = 'inputs/interview/sections/subjects_pane.html'
    _ERRORS_TEMPLATE = 'inputs/interview/sections/subjects_errors.html'
    _FILING_STATUS   = 'filing-status'
    _ERRORS          = 'subjects-errors'

    def get( self, request ):
        profile, _plans = _current_profile_and_plans( request )
        return self._response( request, SubjectsForm( profile = profile ) )

    def post( self, request ):
        organization = request.organization
        profile, _plans = _current_profile_and_plans( request )
        form = SubjectsForm( request.POST, profile = profile )
        if not form.is_valid():
            return self._swap( request, form )                 # a half-entered partner
        profile, _plans = form.apply( profile, None )
        save_profile( organization, profile )
        # A clean save clears any stale half-entered-partner warning (the fields are left untouched, so
        # focus is undisturbed) and refreshes the filing-status readout, which a partner change alters.
        label = SubjectsForm( profile = profile ).filing_status_label
        return antinode.response(
            replace_map = { self._ERRORS: render_to_string(
                self._ERRORS_TEMPLATE, { 'subjects_form': form }, request = request ) },
            insert_map  = { self._FILING_STATUS: label } )

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'subjects_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'subjects': render_to_string(
            self._TEMPLATE, { 'subjects_form': form }, request = request ) } )


class PossessionsView( SelfSavingPaneView ):
    """`/inputs/interview/properties/possessions/` -- the Other Possessions list of the Property pane.
    Its item set can change, so a save that adds or removes a row re-renders the pane; an incomplete
    row simply does not materialize."""

    template     = 'inputs/interview/sections/possessions.html'
    target       = 'possessions'
    context_name = 'possessions_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return PossessionsForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = self._count( profile )
        profile, _plans = form.apply( profile, plans )
        save_profile( request.organization, profile )
        return self._count( profile ) != before                # a row was added or removed

    @staticmethod
    def _count( profile ) -> int:
        return sum( 1 for asset in profile.assets if asset.asset_class in PossessionsForm._CLASSES )


class DebtsView( SelfSavingPaneView ):
    """`/inputs/interview/debt/list/` -- the debts list of the Debts section. Its debt set can change,
    so a save that adds or removes a row re-renders the list; an incomplete row simply does not
    materialize. Mortgages edit here like any other debt; each row preserves its stable handle and any
    property it is secured against."""

    template     = 'inputs/interview/sections/debts_list.html'
    target       = 'debts-list'
    context_name = 'debts_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return DebtsForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = len( profile.debts )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )     # a removed debt reaps its plan too
        return len( profile.debts ) != before                  # a row was added or removed


class DebtPlanView( SelfSavingPaneView ):
    """`/inputs/interview/debt/plan/` -- the per-debt repayment terms of the Debt plan section. It
    persists the repayment/prepayment plans; the row set is fixed by the declared debts, so incomplete
    terms simply do not materialize a loan."""

    template     = 'inputs/interview/sections/debt_plan_list.html'
    target       = 'debt-plan'
    context_name = 'debt_plan_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return DebtPlanForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


class CreditCardView( SelfSavingPaneView ):
    """`/inputs/interview/debt/cards/` -- the per-card paydown calculators of the Debt plan section. It
    persists the card plans; the card set is fixed by the declared debts (the mode switch and the live
    readout are client-side), so a half-entered strategy simply stores no plan."""

    template     = 'inputs/interview/sections/credit_card_list.html'
    target       = 'credit-card-plan'
    context_name = 'credit_card_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return CreditCardPlanForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


class IncomeTableView( SelfSavingPaneView ):
    """`/inputs/interview/income/table/` -- the §5 income table. Its line set can change, so a save
    that adds or removes a line re-renders the pane; a pure value edit stays silent. The age<->date
    sync is done client-side (`inputs.js`)."""

    template     = 'inputs/interview/sections/income_table.html'
    target       = 'income-table'
    context_name = 'income_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return IncomeTableForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = self._line_count( profile )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return self._line_count( profile ) != before           # a line was added or removed

    @staticmethod
    def _line_count( profile ) -> int:
        """The general income lines (the only rows whose count changes); rental and entitlement rows
        are fixed by the properties and subjects."""
        return sum( 1 for flow in profile.income_flows if flow.property_handle is None )


@method_decorator( ensure_organization, name = 'dispatch' )
class _PropertyView( View ):
    """Shared, org-scoped base for the mortgaged-property panes: it renders the property list from the
    pane's holdings and template config. A concrete view binds a `_PANE` (see `PropertyPane`) that
    supplies the form class, holding asset class, DOM ids, and URL names."""

    _PANE          : PropertyPane
    _LIST_TEMPLATE = 'inputs/interview/sections/property_list.html'

    def _list( self, request, profile ):
        return render_to_string(
            self._LIST_TEMPLATE,
            { 'properties': properties_context( profile, self._PANE.asset_class ),
              **self._PANE.template_context() },
            request = request )


class _PropertyFormView( _PropertyView ):
    """The add/edit form for one mortgaged property in the Property pane. Add and edit converge:
    GET-add mints a fresh handle and opens the editor for it, so the form always edits a known handle
    and a new property has a stable identity from the first keystroke. POST auto-saves in the
    background -- non-blocking, so an incomplete (or never-filled) property writes nothing -- and just
    refreshes the list; the open form is left untouched except to surface a genuine field error."""

    _FORM_TEMPLATE = 'inputs/interview/sections/property_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._form( request, None, None ) )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_handle( profile, self._PANE.form._PREFIX )
        form = self._PANE.form( profile = profile, plans = plans, handle = handle )
        return antinode.response( main_content = self._form( request, handle, form ) )

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = self._PANE.form( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { self._PANE.form_id: self._form( request, handle, form ) } )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        # Leave the open form alone; just refresh the list by id, where a property appears, updates its
        # name/value, or -- if edited to incomplete -- drops out.
        return antinode.response( replace_map = { self._PANE.list_id: self._list( request, profile ) } )

    def _form( self, request, handle, form ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'property_form': form, 'handle': handle, **self._PANE.template_context() },
            request = request )


class _PropertyDeleteView( _PropertyView ):
    """Remove a mortgaged property as a unit, then refresh its list in place."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = delete_property( profile, plans, handle )
        _save_profile_and_plans( request, profile, plans )
        # Refresh the list by id (replace, not insert) so the re-rendered `<div id=list_id>` swaps the
        # existing one rather than nesting inside it.
        return antinode.response(
            replace_map = { self._PANE.list_id: self._list( request, profile ) } )


class RentalFormView( _PropertyFormView ):
    """`/inputs/interview/properties/rentals/add/` and `.../<handle>/`."""

    _PANE = RENTAL_PANE


class RentalDeleteView( _PropertyDeleteView ):
    """`/inputs/interview/properties/rentals/<handle>/delete/`."""

    _PANE = RENTAL_PANE


class SecondHomeFormView( _PropertyFormView ):
    """`/inputs/interview/properties/second-homes/add/` and `.../<handle>/`."""

    _PANE = SECOND_HOME_PANE


class SecondHomeDeleteView( _PropertyDeleteView ):
    """`/inputs/interview/properties/second-homes/<handle>/delete/`."""

    _PANE = SECOND_HOME_PANE


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
        profile, _ = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._menu( request, profile ) )
        form = EventForm( event_type = self._event_type( kind ), profile = profile )
        return antinode.response( main_content = self._form( request, kind, form ) )

    def post( self, request, kind ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        event_type = self._event_type( kind )
        form = EventForm( request.POST, event_type = event_type, profile = profile )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, kind, form ) )
        original = profile
        profile, event = event_type.provision( form.build_event(), profile )
        profile, plans = event_type.cascade_on_add( event, profile, plans )
        plans = replace( plans, events = list( plans.events ) + [ event ] )
        with transaction.atomic():
            if profile is not original:   # provision created an entity, or a cascade adjusted facts
                save_profile( organization, profile )
            save_plans( current_plans_record( request ), plans )
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
        profile, plans = _current_profile_and_plans( request )
        events = list( plans.events )
        if 0 <= index < len( events ):
            original = profile
            removed  = events[ index ]
            profile, plans = handler_for( removed.kind ).cascade_on_remove(
                removed, profile, plans )
            del events[ index ]
            plans = replace( plans, events = events )
            with transaction.atomic():
                if profile is not original:
                    save_profile( organization, profile )
                save_plans( current_plans_record( request ), plans )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) },
            request = request ) )
