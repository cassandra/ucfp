"""The inputs area -- the hub plus the guided interview and its per-flow editors.

The hub (`/inputs/`) lists the current Profile and the organization's Plans and Assumptions sets,
each linking to its flow. The interview is one section machinery run as three flows (Profile, Plans,
Assumptions): `FlowEntryView` enters a single flow, `InterviewHomeView` runs all three guided, and
`InterviewView` drives one section at a time over the typed aggregates. The remaining views are the
sub-editors each section pane drills into.
"""
from dataclasses import replace

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
    create_plans, latest_plans, load_plans, plans_for, save_plans )
from ucfp.inputs.assumptions.repository import (
    assumptions_for, create_assumptions, latest_assumptions, load_assumptions, save_assumptions )
from ucfp.inputs.plans.enums import EventKind

from .interview import (
    SECTIONS, Aggregate, AccountsForm, HomeForm, SubjectsForm, applicable_sections,
    first_section_of_flow, flow_of, flow_title, next_flow_entry, next_section_after, section_for )
from .models import AssumptionsRecord, PlansRecord
from .auto import AutoPlanForm
from .credit_card import CreditCardPlanForm
from .external_factors import ExternalFactorsForm
from .debt_plan import DebtPlanForm
from .debts import DebtsForm
from .events import EventForm, events_context, handler_for, menu_context
from .income import IncomeTableForm
from .properties import (
    RENTAL_PANE, SECOND_HOME_PANE, PossessionsForm, PropertyPane, _minted_handle, delete_property,
    properties_context )
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


def _select( request, field, record ):
    """Make `record` the current editing target for its aggregate (by session `field`), so the flow
    edits it. The single place a plans/assumptions selection is recorded."""
    setattr( request.session_state, field, str( record.uuid ) )
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
        profile, other = self._load( request, current )
        sections = self._flow_sections( profile, flow_of( current ) )
        form     = self._form( current, profile, other )
        if is_ajax( request ):
            return self._swap( request, sections, current, form )
        return render( request, self._PAGE_TEMPLATE, self._context( request, sections, current, form ) )

    def post( self, request, section ):
        current = self._live_section( section )
        flow = flow_of( current )
        profile, other = self._load( request, current )
        form = self._form( current, profile, other, request.POST )
        if not form.is_valid():
            return self._swap( request, self._flow_sections( profile, flow ), current, form )
        profile   = self._store( request, current, form, profile, other )
        following = next_section_after( self._flow_sections( profile, flow ), current.key )
        if following is None and request.session.get( 'interview_guided' ):
            following = next_flow_entry( flow )         # guided: advance into the next flow
        if following is None:
            return antinode.redirect_response( reverse( 'inputs_home' ) )
        next_sections = self._flow_sections( profile, flow_of( following ) )
        next_profile, next_other = self._load( request, following )
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
            'sections'        : sections,
            'current_section' : section,
            'flow_title'      : flow_title( flow ),
            'flow_heading'    : self._flow_heading( request, flow ),
            'form'            : form,
            'section_target'  : self._SECTION_TARGET,
            'stepper_target'  : self._STEPPER_TARGET,
        }

    @staticmethod
    def _flow_heading( request, flow ) -> str:
        """The flow's title with the record being edited named, for the page heading -- "Plans: Base
        case", "Assumptions: Optimistic" -- so the user sees which of several they are editing. The
        single-record Profile shows just its title."""
        title = flow_title( flow )
        if flow == 'plans':
            return f'{title}: {current_plans_record( request ).label}'
        if flow == 'assumptions':
            return f'{title}: {current_assumptions_record( request ).label}'
        return title


@method_decorator( ensure_organization, name = 'dispatch' )
class AutoPlanView( View ):
    """`/inputs/interview/spending/auto-purchases/` -- the car-purchase/financing pane of the Spending
    section (a special case, distinct from the generic 'auto' expense category and its
    `spending/auto/` route). POST auto-saves a single edit in the background: it persists the auto
    plan and replies silently, re-rendering the pane only on a genuine field error. Validation is
    non-blocking, so an incomplete plan simply stores nothing."""

    _TEMPLATE = 'inputs/interview/sections/auto_plan.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'auto_form': AutoPlanForm( profile = profile, plans = plans ) },
            request = request ) )

    def post( self, request ):
        profile, plans = _current_profile_and_plans( request )
        form = AutoPlanForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return antinode.response( replace_map = { 'auto-purchases': render_to_string(
                self._TEMPLATE, { 'auto_form': form }, request = request ) } )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ),plans )
        return antinode.response()                             # silent background save


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
        profile, plans = _current_profile_and_plans( request )
        form = GroupSpendingForm(
            profile = profile, plans = plans, group = self._group( profile, group ) )
        return self._editor_response( request, group, form )

    def post( self, request, group ):
        profile, plans = _current_profile_and_plans( request )
        form = GroupSpendingForm(
            request.POST, profile = profile, plans = plans,
            group = self._group( profile, group ) )
        if form.is_valid():
            _, updated = form.apply( profile, plans )
            save_plans( current_plans_record( request ),updated )
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
    else the latest, minting one if the org has none. The twin of `current_plans_record`."""
    organization = request.organization
    uuid = request.session_state.current_assumptions_uuid
    if uuid is not None:
        selected = assumptions_for( organization ).filter( uuid = uuid ).first()
        if selected is not None:
            return selected
    return latest_assumptions( organization ) or create_assumptions( organization )


def _current_profile_and_plans( request ):
    """The user's current Profile and the contents of the Plans record they are editing, creating
    either if absent."""
    profile = load_profile( latest_profile( request.organization ) or create_profile( request.organization ) )
    return profile, load_plans( current_plans_record( request ) )


def _current_assumptions( request ):
    """The contents of the Assumptions record the user is editing, creating it if absent."""
    return load_assumptions( current_assumptions_record( request ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class ResidenceView( View ):
    """`/inputs/interview/properties/residence/` -- the residence sub-form of the Property pane. POST
    auto-saves a single edit in the background: it persists just the residence (its asset, mortgage,
    and rent) and replies silently, re-rendering the sub-pane only on a genuine field error. Own/rent
    and mortgage visibility are client-side (`inputs.js`); validation is non-blocking, so an
    incomplete residence simply does not materialize (the forecast run is the real gate)."""

    _TEMPLATE = 'inputs/interview/sections/residence.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._response( request, HomeForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        form = HomeForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )
        return antinode.response()                             # silent background save

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'residence_form': form }, request = request ) )

    def _swap( self, request, form ):
        # Replace the pane by id (not a data-async target) so the loader-suppressed background POST,
        # which carries no target, still applies the re-render.
        return antinode.response( replace_map = { 'residence': render_to_string(
            self._TEMPLATE, { 'residence_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class ExternalFactorsView( View ):
    """`/inputs/interview/external-factors/edit/` -- the External Factors pane of the Assumptions flow.
    POST auto-saves a single edit in the background: it persists the assumptions' economic factors and
    tax projection and replies silently, re-rendering the pane only on a genuine field error.
    Validation is non-blocking -- an incomplete factor simply is not saved; the forecast readiness
    check is the completeness gate."""

    _TEMPLATE = 'inputs/interview/sections/external_factors_pane.html'

    def get( self, request ):
        return self._response(
            request, ExternalFactorsForm( assumptions = _current_assumptions( request ) ) )

    def post( self, request ):
        assumptions = _current_assumptions( request )
        form = ExternalFactorsForm( request.POST, assumptions = assumptions )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        _profile, assumptions = form.apply( None, assumptions )
        save_assumptions( current_assumptions_record( request ), assumptions )
        return antinode.response()                             # silent background save

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'factors_form': form }, request = request ) )

    def _swap( self, request, form ):
        # Replace the pane by id (not a data-async target) so the loader-suppressed background POST,
        # which carries no target, still applies the re-render.
        return antinode.response( replace_map = { 'external-factors': render_to_string(
            self._TEMPLATE, { 'factors_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class AccountsView( View ):
    """`/inputs/interview/accounts/edit/` -- the Accounts pane of the Profile flow. POST auto-saves a
    single edit in the background: it persists the household's account balances and replies silently,
    re-rendering the pane only on a genuine field error. Validation is non-blocking -- a blank account
    is simply not held; the forecast readiness check is the completeness gate."""

    _TEMPLATE = 'inputs/interview/sections/accounts_pane.html'

    def get( self, request ):
        profile, _plans = _current_profile_and_plans( request )
        return self._response( request, AccountsForm( profile = profile ) )

    def post( self, request ):
        organization = request.organization
        profile, _plans = _current_profile_and_plans( request )
        form = AccountsForm( request.POST, profile = profile )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        profile, _plans = form.apply( profile, None )
        save_profile( organization, profile )
        return antinode.response()                             # silent background save

    def _response( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'accounts_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'accounts': render_to_string(
            self._TEMPLATE, { 'accounts_form': form }, request = request ) } )


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


@method_decorator( ensure_organization, name = 'dispatch' )
class PossessionsView( View ):
    """`/inputs/interview/properties/possessions/` -- the Other Possessions list of the Property pane.
    POST auto-saves a single edit in the background: it persists and replies silently, re-rendering the
    pane only when the item set changed (a row added or removed) or a field failed validation.
    Validation is non-blocking, so an incomplete row simply does not materialize."""

    _TEMPLATE = 'inputs/interview/sections/possessions.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._rendered( request, PossessionsForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        form = PossessionsForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # show a bad value
        before = self._count( profile )
        profile, _plans = form.apply( profile, plans )
        save_profile( organization, profile )
        if self._count( profile ) != before:                   # a row was added or removed
            return self._swap( request, PossessionsForm( profile = profile, plans = plans ) )
        return antinode.response()                             # silent: nothing to re-render

    @staticmethod
    def _count( profile ) -> int:
        return sum( 1 for asset in profile.assets if asset.asset_class in PossessionsForm._CLASSES )

    def _rendered( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'possessions_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'possessions': render_to_string(
            self._TEMPLATE, { 'possessions_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class DebtsView( View ):
    """`/inputs/interview/debt/list/` -- the debts list of the Debts section. POST auto-saves a
    single edit in the background: it persists and replies silently, re-rendering the list only when
    the debt set changed (a row added or removed) or a field failed validation. Validation is
    non-blocking, so an incomplete row simply does not materialize. Mortgages edit here like any
    other debt; each row preserves its stable handle and any property it is secured against."""

    _TEMPLATE = 'inputs/interview/sections/debts_list.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._rendered( request, DebtsForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        form = DebtsForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # show a bad value
        before = len( profile.debts )
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )      # a removed debt reaps its plan too
        if len( profile.debts ) != before:                     # a row was added or removed
            return self._swap( request, DebtsForm( profile = profile, plans = plans ) )
        return antinode.response()                             # silent: nothing to re-render

    def _rendered( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'debts_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'debts-list': render_to_string(
            self._TEMPLATE, { 'debts_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class DebtPlanView( View ):
    """`/inputs/interview/debt/plan/` -- the per-debt repayment terms of the Debt plan section. POST
    auto-saves a single edit in the background: it persists the repayment/prepayment plans and replies
    silently, re-rendering the pane only on a genuine field error (the row set is fixed by the declared
    debts, so nothing is added or removed here). Validation is non-blocking, so incomplete terms simply
    do not materialize a loan."""

    _TEMPLATE = 'inputs/interview/sections/debt_plan_list.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._rendered( request, DebtPlanForm( profile = profile, plans = plans ) )

    def post( self, request ):
        profile, plans = _current_profile_and_plans( request )
        form = DebtPlanForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ),plans )
        return antinode.response()                             # silent background save

    def _rendered( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'debt_plan_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'debt-plan': render_to_string(
            self._TEMPLATE, { 'debt_plan_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class CreditCardView( View ):
    """`/inputs/interview/debt/cards/` -- the per-card paydown calculators of the Debt plan section.
    POST auto-saves a single edit in the background: it persists the card plans and replies silently,
    re-rendering the pane only on a genuine field error (the card set is fixed by the declared debts;
    the mode switch and the live readout are client-side). Validation is non-blocking, so a
    half-entered strategy simply stores no plan."""

    _TEMPLATE = 'inputs/interview/sections/credit_card_list.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._rendered( request, CreditCardPlanForm( profile = profile, plans = plans ) )

    def post( self, request ):
        profile, plans = _current_profile_and_plans( request )
        form = CreditCardPlanForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # surface a genuine field error
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ),plans )
        return antinode.response()                             # silent background save

    def _rendered( self, request, form ):
        return antinode.response( main_content = render_to_string(
            self._TEMPLATE, { 'credit_card_form': form }, request = request ) )

    def _swap( self, request, form ):
        return antinode.response( replace_map = { 'credit-card-plan': render_to_string(
            self._TEMPLATE, { 'credit_card_form': form }, request = request ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class IncomeTableView( View ):
    """`/inputs/interview/income/table/` -- the §5 income table. GET renders it. POST auto-saves a
    single edit in the background: it persists, then replies *silently* (an empty antinode response,
    no DOM swap) for a pure value edit so typing flow is undisturbed, and re-renders the pane only
    when the row set changed (a line added or removed) or a field failed validation -- cases the
    client cannot reflect on its own. The age<->date sync is done client-side (`inputs.js`)."""

    _TEMPLATE = 'inputs/interview/sections/income_table.html'

    def get( self, request ):
        profile, plans = _current_profile_and_plans( request )
        return self._rendered( request, IncomeTableForm( profile = profile, plans = plans ) )

    def post( self, request ):
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        form = IncomeTableForm( request.POST, profile = profile, plans = plans )
        if not form.is_valid():
            return self._swap( request, form )                 # show field errors
        before = self._line_count( profile )
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )
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
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        form = self._PANE.form( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { self._PANE.form_id: self._form( request, handle, form ) } )
        profile, plans = form.apply( profile, plans )
        save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )
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
        organization = request.organization
        profile, plans = _current_profile_and_plans( request )
        profile, plans = delete_property( profile, plans, handle )
        save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )
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
        if profile is not original:   # provision created an entity, or a cascade adjusted facts
            save_profile( organization, profile )
        save_plans( current_plans_record( request ),plans )
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
            if profile is not original:
                save_profile( organization, profile )
            save_plans( current_plans_record( request ),plans )
        return antinode.response( main_content = render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) },
            request = request ) )
