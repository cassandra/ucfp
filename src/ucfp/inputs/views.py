"""The inputs area -- the Scenarios landing plus the section interview and its per-flow editors.

The Scenarios landing (`/inputs/scenarios/`) lists the organization's scenarios and hosts the Plans and
Assumptions management; the Profile is edited on its own flow (reached from the nav). The interview is
one section machinery run as three flows (Profile, Plans, Assumptions): `FlowEntryView` enters a single
flow and `InterviewView` drives one section at a time over the typed aggregates. Profile is the
standalone first setup; the Plans/Assumptions flows compose into a scenario (the build flow chains them).
The remaining views are the sub-editors each section pane drills into.
"""
from collections import Counter
from dataclasses import replace

from django import forms
from django.core.exceptions import BadRequest
from django.db import transaction
from django.db.models import Prefetch
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
from ucfp.inputs.scenarios.repository import (
    clone_scenario, create_fresh_scenario, create_scenario, delete_scenario, ensure_default_scenario,
    existing_pairings, rename_scenario, scenarios_for, would_orphan_all_scenarios )
from ucfp.inputs.plans.enums import EventKind

from .interview import (
    Aggregate, AccountsForm, HomeForm, SubjectsForm, applicable_sections,
    first_section_of_flow, flow_of, flow_title, next_section_after, section_for )
from .enums import UsageRole
from .models import AssumptionsRecord, PlansRecord, ScenarioRecord
from .state import (
    completed_assumptions, completed_plans, completed_profile, flow_reviewed, profile_is_complete )
from .vehicle import VehicleForm, delete_vehicle, vehicles_context, _minted_vehicle_handle
from .vehicle_expenses import VehicleExpensesForm
from .credit_card import CreditCardPlanForm
from .retirement_plans import ContributionsForm, ConversionsForm, WithdrawalsForm
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
from .retirement import RetirementForm

_SCENARIOS_TEMPLATE = 'inputs/scenarios_home.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenariosHomeView( View ):
    """`/inputs/scenarios/` -- the Scenarios landing: the organization's saved scenarios, plus the Plans
    and Assumptions management (a scenario is a combination of those, so its components are managed here).
    A placeholder for now -- scenario building and per-scenario management arrive later; this only lists
    them and keeps the component editors reachable. Perspective-agnostic: it links to the component
    editors but to no planning perspective (forecast, retirement, ...) -- the main nav reaches those."""

    def get( self, request ):
        organization   = request.organization
        profile_record = completed_profile( organization )
        profile        = load_profile( profile_record ) if profile_record is not None else None
        # One pass over the saved scenarios drives both the scenario cards and the component rows: the
        # per-component usage counts feed the "shared" indicator and, against the scenario total, the
        # `deletable` flag -- so the page needs no per-row query to decide either.
        scenarios        = list( scenarios_for( organization ).select_related( 'plans', 'assumptions' ) )
        plans_uses       = Counter( scenario.plans_id for scenario in scenarios )
        assumptions_uses = Counter( scenario.assumptions_id for scenario in scenarios )
        plans       = self._component_rows(
            plans_for( organization ), profile, 'plans', plans_uses, len( scenarios ) )
        assumptions = self._component_rows(
            assumptions_for( organization ), profile, 'assumptions', assumptions_uses, len( scenarios ) )
        complete_ids  = ( { row[ 'record' ].id for row in plans if row[ 'complete' ] },
                          { row[ 'record' ].id for row in assumptions if row[ 'complete' ] } )
        scenario_rows = self._scenario_rows( scenarios, plans_uses, assumptions_uses, *complete_ids )
        return render( request, _SCENARIOS_TEMPLATE, {
            'active_nav'       : 'scenarios',
            # Building a scenario needs a completed profile first, so the page leads with the profile gate.
            'profile_complete' : profile_record is not None,
            'scenarios'        : scenario_rows,
            'plans'            : plans,
            'assumptions'      : assumptions,
            # A household keeps at least one scenario, so its sole scenario's delete control is suppressed.
            'can_delete_scenario' : len( scenarios ) > 1,
        } )

    @staticmethod
    def _component_rows( records, profile, flow, uses, scenario_count ):
        """Each component as a `{record, complete, deletable}` row. `complete` when its flow is fully walked
        (an incomplete component is absent from scenario building; None profile means no completeness -- the
        profile gate shows instead). `deletable` mirrors the delete guards in the UI: false for the last of
        its kind, and false for a set every scenario pairs (whose deletion would cascade the org's last
        scenario away) -- i.e. when its use-count equals `scenario_count`. `uses` maps a component's id to
        how many scenarios pair it. The prefetch is scoped to SAVED scenarios so the delete-cascade warning
        counts the same scenarios the guard does."""
        saved    = Prefetch(
            'scenarios', queryset = ScenarioRecord.objects.filter( usage_role = UsageRole.SAVED ) )
        records  = list( records.prefetch_related( saved ) )
        multiple = len( records ) > 1
        rows = list()
        for record in records:
            paired_by_every_scenario = scenario_count > 0 and uses[ record.id ] == scenario_count
            rows.append( { 'record': record,
                           'complete': profile is not None and flow_reviewed( profile, record, flow ),
                           'deletable': multiple and not paired_by_every_scenario } )
        return rows

    @staticmethod
    def _scenario_rows( scenarios, plans_uses, assumptions_uses, plans_ids, assumptions_ids ):
        """Each saved scenario as a row -- `complete` (both components' flows walked, so an in-progress one
        can offer to resume setup) plus how many scenarios share each of its components (`plans_uses` /
        `assumptions_uses`), which drives the "shared" indicator. `scenarios` and the usage counters are
        prepared once by the caller so the page makes a single scenarios query."""
        rows = list()
        for scenario in scenarios:
            complete = scenario.plans_id in plans_ids and scenario.assumptions_id in assumptions_ids
            rows.append( { 'scenario': scenario, 'complete': complete,
                           'plans_uses': plans_uses[ scenario.plans_id ],
                           'assumptions_uses': assumptions_uses[ scenario.assumptions_id ] } )
        return rows


_RENAME_PANE = 'inputs/panes/inline_rename.html'


def _rename_or_conflict( request, record, *, siblings, kind, aria, bold, rename ):
    """Apply an inline rename unless the new name is already used by another of `siblings` (same type, same
    organization). A valid rename (or a blank, ignored) saves silently, so the field keeps focus while
    editing; only a duplicate re-renders the pane -- reverting the field with a warning. Editing the field
    clears that warning client-side (see the js-rename handler), so no re-render on success is needed."""
    label = request.POST.get( 'label', '' ).strip()
    if not label:
        return antinode.response()
    if not siblings.filter( label__iexact = label ).exclude( pk = record.pk ).exists():
        rename( record, label )
        return antinode.response()
    pane = render_to_string( _RENAME_PANE, {
        'kind': kind, 'uuid': record.uuid, 'rename_url': request.path, 'label': record.label,
        'aria': aria, 'bold': bold, 'warning': 'That name is already in use.' }, request = request )
    return antinode.response( replace_map = { f'rename-{kind}-{record.uuid}': pane } )


def _redirect_to_profile_setup( request ):
    """Send a user without a complete Profile to set one up -- the universal prerequisite for building or
    combining a scenario. No return is stashed: the Profile flow ends on its own landing (the user then
    heads to the feature via the nav), so a return here would not be honoured."""
    return redirect( 'flow_profile' )


class _NamedScenarioForm( forms.Form ):
    """Shared name field + duplicate-name check for the scenario-creation forms."""

    name = forms.CharField( label = 'Scenario name', max_length = 255 )

    def __init__( self, *args, taken_names = frozenset(), **kwargs ):
        super().__init__( *args, **kwargs )
        self._taken_names = taken_names
        self.fields[ 'name' ].widget.attrs[ 'class' ] = 'form-control'

    def clean_name( self ):
        name = self.cleaned_data[ 'name' ].strip()
        if name.lower() in self._taken_names:
            raise forms.ValidationError( 'A scenario with that name already exists -- pick another.' )
        return name


class PairScenarioForm( _NamedScenarioForm ):
    """Pair an existing complete Plans with an existing complete Assumptions into a new named scenario. The
    choosers (injected by the view) are the complete components; the cascading UI keeps the pick to a
    not-yet-used combination, and this re-checks server-side."""

    plans       = forms.ChoiceField( label = 'Plans' )
    assumptions = forms.ChoiceField( label = 'Assumptions' )

    def __init__( self, *args, plans = None, assumptions = None, taken = frozenset(), **kwargs ):
        super().__init__( *args, **kwargs )
        self._taken = taken
        self.fields[ 'plans' ].choices = [
            ( str( record.uuid ), record.label ) for record in ( plans or [] ) ]
        self.fields[ 'assumptions' ].choices = [
            ( str( record.uuid ), record.label ) for record in ( assumptions or [] ) ]
        for field in ( 'plans', 'assumptions' ):
            self.fields[ field ].widget.attrs[ 'class' ] = 'custom-select'

    def clean( self ):
        cleaned = super().clean()
        pairing = ( cleaned.get( 'plans' ), cleaned.get( 'assumptions' ) )
        if None not in pairing and pairing in self._taken:
            raise forms.ValidationError(
                'That combination is already a scenario -- pick a different Plans or Assumptions.' )
        return cleaned


class CopyScenarioForm( _NamedScenarioForm ):
    """Copy an existing scenario into a new one, choosing per side whether to Copy (clone, then editable) or
    Reuse (share) its Plans and its Assumptions. At least one side must be copied -- reusing both would just
    re-create the source's own pairing."""

    _MODE_CHOICES = [ ( 'copy', 'Copy to edit' ), ( 'reuse', 'Reuse (shared)' ) ]

    source           = forms.ChoiceField( label = 'Copy from' )
    plans_mode       = forms.ChoiceField(
        label = 'Plans', choices = _MODE_CHOICES, initial = 'copy', widget = forms.RadioSelect )
    assumptions_mode = forms.ChoiceField(
        label = 'Assumptions', choices = _MODE_CHOICES, initial = 'copy', widget = forms.RadioSelect )

    def __init__( self, *args, scenarios = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self._by_uuid = { str( record.uuid ): record for record in ( scenarios or [] ) }
        self.fields[ 'source' ].choices = [
            ( uuid, record.label ) for uuid, record in self._by_uuid.items() ]
        self.fields[ 'source' ].widget.attrs[ 'class' ] = 'custom-select'

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'plans_mode' ) == 'reuse' and cleaned.get( 'assumptions_mode' ) == 'reuse':
            raise forms.ValidationError(
                'Copy at least one of Plans or Assumptions -- reusing both would re-create this scenario.' )
        return cleaned

    @property
    def source_scenario( self ):
        return self._by_uuid[ self.cleaned_data[ 'source' ] ]


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioComposeView( View ):
    """`/inputs/scenarios/compose/` -- New scenario. Three ways to create one: **Pair** existing complete
    components into a not-yet-used combination (when free pairings exist), **Copy** an existing scenario
    (per side, copy or reuse), or **Start fresh** (new default Plans + Assumptions, then the interview).
    A completed Profile is the prerequisite; until a first scenario is complete the page steers the user to
    finish that one rather than pile up more."""

    _TEMPLATE = 'inputs/scenario_compose.html'

    def get( self, request ):
        profile_record = completed_profile( request.organization )
        if profile_record is None:
            return _redirect_to_profile_setup( request )
        return render( request, self._TEMPLATE, self._context( request.organization, profile_record ) )

    def post( self, request ):
        profile_record = completed_profile( request.organization )
        if profile_record is None:
            return _redirect_to_profile_setup( request )
        handler = { 'start_fresh': self._start_fresh, 'copy': self._copy, 'pair': self._pair }.get(
            request.POST.get( 'action' ) )
        if handler is None:
            raise BadRequest( 'Unknown scenario-creation action.' )
        return handler( request, profile_record )

    def _start_fresh( self, request, profile_record ):
        scenario = create_fresh_scenario( request.organization, request.POST.get( 'name' ) or None )
        return _enter_scenario_build( request, scenario )

    def _copy( self, request, profile_record ):
        form = CopyScenarioForm(
            request.POST, prefix = 'copy',
            scenarios = self._complete_scenarios( request.organization, profile_record ),
            taken_names = self._taken_names( request.organization ) )
        if not form.is_valid():
            return render(
                request, self._TEMPLATE,
                self._context( request.organization, profile_record, copy_form = form ) )
        clone_scenario(
            form.source_scenario, copy_plans = form.cleaned_data[ 'plans_mode' ] == 'copy',
            copy_assumptions = form.cleaned_data[ 'assumptions_mode' ] == 'copy',
            label = form.cleaned_data[ 'name' ] )
        return redirect( 'scenarios_home' )

    def _pair( self, request, profile_record ):
        plans, assumptions = self._complete_components( request.organization, profile_record )
        form = PairScenarioForm(
            request.POST, prefix = 'pair', plans = plans, assumptions = assumptions,
            taken = existing_pairings( request.organization ),
            taken_names = self._taken_names( request.organization ) )
        if not form.is_valid():
            return render(
                request, self._TEMPLATE,
                self._context( request.organization, profile_record, pair_form = form ) )
        by_plans       = { str( record.uuid ): record for record in plans }
        by_assumptions = { str( record.uuid ): record for record in assumptions }
        create_scenario(
            request.organization, by_plans[ form.cleaned_data[ 'plans' ] ],
            by_assumptions[ form.cleaned_data[ 'assumptions' ] ], form.cleaned_data[ 'name' ] )
        return redirect( 'scenarios_home' )

    def _context( self, organization, profile_record, copy_form = None, pair_form = None ):
        plans, assumptions = self._complete_components( organization, profile_record )
        complete_scenarios = self._complete_scenarios( organization, profile_record )
        available          = self._available_assumptions( organization, plans, assumptions )
        taken_names        = self._taken_names( organization )
        pairable_plans     = [ record for record in plans if available[ str( record.uuid ) ] ]
        return {
            'active_nav'            : 'scenarios',
            'has_complete_scenario' : bool( complete_scenarios ),
            'incomplete_scenarios'  : self._incomplete_scenarios( organization, profile_record ),
            'can_pair'              : bool( pairable_plans ),
            'pair_form'             : pair_form or PairScenarioForm(
                prefix = 'pair', plans = pairable_plans, assumptions = assumptions,
                taken = existing_pairings( organization ), taken_names = taken_names ),
            'copy_form'             : copy_form or CopyScenarioForm(
                prefix = 'copy', scenarios = complete_scenarios, taken_names = taken_names ),
            # Option rows for the manually-rendered selects: the source scenarios (with the component labels
            # the Copy card reflects), the pairable Plans (each carrying the free Assumptions to filter to),
            # and the Assumptions choices. Data rides on the options, read by inputs.js.
            'copy_sources'          : [
                { 'uuid': str( scenario.uuid ), 'label': scenario.label,
                  'plans': scenario.plans.label, 'assumptions': scenario.assumptions.label }
                for scenario in complete_scenarios ],
            'pair_plans'            : [
                { 'uuid': str( record.uuid ), 'label': record.label,
                  'available': ','.join( available[ str( record.uuid ) ] ) }
                for record in pairable_plans ],
            'pair_assumptions'      : [
                { 'uuid': str( record.uuid ), 'label': record.label } for record in assumptions ],
        }

    @staticmethod
    def _complete_components( organization, profile_record ):
        return ( completed_plans( profile_record, organization ),
                 completed_assumptions( profile_record, organization ) )

    def _complete_scenarios( self, organization, profile_record ):
        """The organization's saved scenarios whose Plans and Assumptions are both complete -- the ones a
        Copy can start from."""
        plans, assumptions = self._complete_components( organization, profile_record )
        plan_ids           = { record.id for record in plans }
        assumption_ids     = { record.id for record in assumptions }
        return [ scenario for scenario in scenarios_for( organization ).select_related( 'plans', 'assumptions' )
                 if scenario.plans_id in plan_ids and scenario.assumptions_id in assumption_ids ]

    def _incomplete_scenarios( self, organization, profile_record ):
        """Saved scenarios not yet fully set up -- surfaced so the user knows why their in-progress
        components are not available to pair."""
        complete = { scenario.id for scenario in self._complete_scenarios( organization, profile_record ) }
        return [ scenario for scenario in scenarios_for( organization ) if scenario.id not in complete ]

    @staticmethod
    def _available_assumptions( organization, plans, assumptions ):
        """Map each complete Plans's uuid -> the complete Assumptions uuids not yet paired with it, so the
        Pair UI can offer only new combinations."""
        taken = existing_pairings( organization )
        return { str( plan.uuid ): [ str( item.uuid ) for item in assumptions
                                     if ( str( plan.uuid ), str( item.uuid ) ) not in taken ]
                 for plan in plans }

    @staticmethod
    def _taken_names( organization ):
        return { record.label.lower() for record in scenarios_for( organization ) }


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioEditView( View ):
    """`/inputs/scenarios/<uuid>/edit/` -- enter a scenario's build flow (the Edit-scenario operation):
    make its Plans and Assumptions the editing target, mark the build in progress, and (re-)enter the
    two-part flow at the first Plans section (the stepper shows what is already done). One operation
    behind three labels -- build the untouched Default, resume a half-built scenario, or edit a complete
    one. POST, since it changes editing state."""

    def post( self, request, uuid ):
        organization = request.organization
        scenario = get_object_or_404(
            ScenarioRecord, uuid = uuid, organization = organization, usage_role = UsageRole.SAVED )
        return _enter_scenario_build( request, scenario )


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioRenameView( View ):
    """`/inputs/scenarios/<uuid>/rename/` -- rename a scenario from the Scenarios page's inline editor.
    Saves silently; a blank name is ignored and a duplicate is rejected with a warning."""

    def post( self, request, uuid ):
        organization = request.organization
        record = get_object_or_404(
            ScenarioRecord, uuid = uuid, organization = organization, usage_role = UsageRole.SAVED )
        return _rename_or_conflict(
            request, record, siblings = scenarios_for( organization ), kind = 'scenario',
            aria = 'Scenario name', bold = True, rename = rename_scenario )


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioDeleteView( View ):
    """`/inputs/scenarios/<uuid>/delete/` -- delete a scenario (the Scenarios page asks first). Only the
    pairing is removed; its Plans and Assumptions live on for other scenarios. Clears the chooser's stored
    selection if it pointed here."""

    def post( self, request, uuid ):
        record = get_object_or_404(
            ScenarioRecord, uuid = uuid, organization = request.organization, usage_role = UsageRole.SAVED )
        _forget_if_current( request, 'current_scenario_uuid', record )
        delete_scenario( record )
        return redirect( 'scenarios_home' )


@method_decorator( ensure_organization, name = 'dispatch' )
class FlowEntryView( View ):
    """`/inputs/<flow>/` -- edit a single input flow (Profile, Plans, or Assumptions) on its own. `flow`
    is set per route via `as_view`. Profile is the standalone first flow; Plans/Assumptions are edited on
    their own here (and, in the scenario-building flow, chained -- see `InterviewView`).

    Entering the Profile flow binds the Profile to the organization's Default scenario: it ensures a
    Default Plans + Assumptions + Scenario exist and makes those components the editing target, so the
    profile's straddle sections (Property, Income) write their shared, profile-derived data into the
    Default's Plans rather than minting a stray one."""

    flow = None

    def get( self, request ):
        # A standalone flow is not a scenario build. Clear any build scope left over from an abandoned
        # build, so a lone Plans edit does not wrongly chain into Assumptions (nor show the build
        # breadcrumb, nor finish on the Scenarios page). The scenario build enters through
        # `ScenarioEditView`, which sets the scope -- never through here.
        request.session_state.editing_scenario = None
        request.session_state.to_session( request )
        if self.flow == 'profile':
            default = ensure_default_scenario( request.organization )
            _select( request, 'current_plans_uuid', default.plans )
            _select( request, 'current_assumptions_uuid', default.assumptions )
        first = first_section_of_flow( self.flow )
        if first is None:
            raise Http404( f'No sections in flow {self.flow!r}.' )
        return redirect( 'interview_section', section = first.key )


def _select( request, field, record ):
    """Make `record` the current editing target for its aggregate (by session `field`), so the flow
    edits it. The single place a plans/assumptions selection is recorded."""
    setattr( request.session_state, field, str( record.uuid ) )
    request.session_state.to_session( request )


def _enter_scenario_build( request, scenario ):
    """Make `scenario` the interview's editing target -- its Plans and Assumptions selected and the build
    marked in progress -- and enter the two-part flow at the first Plans section. Shared by the
    edit-a-scenario and start-fresh entries, so both point the flow at that scenario's components rather
    than whatever was selected before."""
    _select( request, 'current_plans_uuid', scenario.plans )
    _select( request, 'current_assumptions_uuid', scenario.assumptions )
    request.session_state.editing_scenario = str( scenario.uuid )
    request.session_state.to_session( request )
    return redirect( 'interview_section', section = first_section_of_flow( 'plans' ).key )


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
class PlansEditView( View ):
    """`/inputs/plans/<uuid>/edit/` -- edit an existing Plans component (Edit-component): make it the
    current editing target and open the standalone Plans flow on it."""

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
class AssumptionsEditView( View ):
    """`/inputs/assumptions/<uuid>/edit/` -- edit an existing Assumptions component (Edit-component):
    make it the current editing target and open the standalone Assumptions flow on it."""

    def get( self, request, uuid ):
        record = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_assumptions_uuid', record )
        return redirect( 'flow_assumptions' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansRenameView( View ):
    """`/inputs/plans/<uuid>/rename/` -- rename a Plans set from the Scenarios page's inline editor. Saves
    silently; a blank name is ignored and a duplicate is rejected with a warning (non-blocking)."""

    def post( self, request, uuid ):
        organization = request.organization
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = organization )
        return _rename_or_conflict(
            request, record, siblings = plans_for( organization ), kind = 'plan', aria = 'Plan name',
            bold = False, rename = rename_plans )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsRenameView( View ):
    """`/inputs/assumptions/<uuid>/rename/` -- rename an assumptions set from the Scenarios page's inline
    editor. Saves silently; a blank name is ignored and a duplicate is rejected with a warning."""

    def post( self, request, uuid ):
        organization = request.organization
        record = get_object_or_404( AssumptionsRecord, uuid = uuid, organization = organization )
        return _rename_or_conflict(
            request, record, siblings = assumptions_for( organization ), kind = 'assumptions',
            aria = 'Assumptions name', bold = False, rename = rename_assumptions )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansCloneView( View ):
    """`/inputs/plans/<uuid>/clone/` -- duplicate a Plans set (its contents plus a "copy" name), make the
    copy the current editing target, and open it for review. POST, since it creates a record. The copy
    starts unreviewed (`reviewed = False`): its values seed the new set, but the user walks each section to
    confirm them before it counts as complete."""

    def post( self, request, uuid ):
        source = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_plans_uuid', clone_plans( source, reviewed = False ) )
        return redirect( 'flow_plans' )


@method_decorator( ensure_organization, name = 'dispatch' )
class AssumptionsCloneView( View ):
    """`/inputs/assumptions/<uuid>/clone/` -- duplicate an Assumptions set (its contents plus a "copy"
    name), make the copy the current editing target, and open it for review. POST, since it creates a
    record. The copy starts unreviewed (`reviewed = False`): its values seed the new set, but the user
    walks each section to confirm them before it counts as complete."""

    def post( self, request, uuid ):
        source = get_object_or_404(
            AssumptionsRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_assumptions_uuid', clone_assumptions( source, reviewed = False ) )
        return redirect( 'flow_assumptions' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansDeleteView( View ):
    """`/inputs/plans/<uuid>/delete/` -- delete a Plans set (destructive; the hub asks first). If it
    was the current editing target, the selection is cleared so the next visit falls back to the
    latest (or a fresh) set."""

    def post( self, request, uuid ):
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        # Deleting cascades away the scenarios that pair this set; refuse if that would leave none.
        if would_orphan_all_scenarios( request.organization, plans = record ):
            raise BadRequest( 'Deleting this Plans set would remove your last scenario.' )
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
        # Deleting cascades away the scenarios that pair this set; refuse if that would leave none.
        if would_orphan_all_scenarios( request.organization, assumptions = record ):
            raise BadRequest( 'Deleting this Assumptions set would remove your last scenario.' )
        _forget_if_current( request, 'current_assumptions_uuid', record )
        delete_assumptions( record )
        return redirect( 'scenarios_home' )


@method_decorator( ensure_organization, name = 'dispatch' )
class InterviewView( View ):
    """`/inputs/interview/<section>/` -- one section of the interview: an antinode-swapped
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
        building  = request.session_state.editing_scenario
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
        Assumptions: clear the in-progress marker and land on the Scenarios page. Finishing the standalone
        Profile loops back to its first section, where the header now shows it is complete; a standalone
        component edit likewise ends on the Scenarios page. Features are reached from the nav, so no flow
        threads a return destination."""
        if building:                                           # end of the two-part build (Assumptions done)
            request.session_state.editing_scenario = None
            request.session_state.to_session( request )
            return reverse( 'scenarios_home' )
        if flow == 'profile':
            first = first_section_of_flow( 'profile' )
            return reverse( 'interview_section', kwargs = { 'section': first.key } )
        return reverse( 'scenarios_home' )

    @staticmethod
    def _editing_scenario_name( request ):
        """The label of the scenario currently being built, or None when no build is in progress -- the
        breadcrumb context for the two-part build flow."""
        uuid = request.session_state.editing_scenario
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
            'flow_heading'         : flow_title( flow ),   # the record's own name is the inline rename below
            # The scenario being built (its name), so the component flows breadcrumb it during a build.
            'editing_scenario_name'    : self._editing_scenario_name( request ),
            # The component being edited, as an inline rename in the header, so its name can be changed
            # here (e.g. straight after a create or clone) rather than only on the Scenarios page.
            'component_rename'     : self._component_rename( request, flow ),
            # The last step of the flow context shows "Finish" rather than "Next" (in a build, the last
            # Plans step chains into Assumptions, so it is not the finish).
            'is_last'              : self._is_last_step( request, sections, section, flow ),
            'form'                 : form,
            'section_target'       : self._SECTION_TARGET,
            'stepper_target'       : self._STEPPER_TARGET,
            **self._profile_status( request, flow ),
        }

    @staticmethod
    def _is_last_step( request, sections, section, flow ) -> bool:
        """Whether this section is the flow context's final step. False for the last Plans step of a build,
        which chains into Assumptions rather than finishing."""
        if next_section_after( sections, section.key ) is not None:
            return False
        return not ( request.session_state.editing_scenario and flow == 'plans' )

    @staticmethod
    def _profile_status( request, flow ) -> dict:
        """The Profile flow's header status -- whether the profile is complete and when it was last
        updated -- so its landing shows setup state. Empty for the component flows."""
        if flow != 'profile':
            return dict()
        record = latest_profile( request.organization )
        return {
            'profile_complete': record is not None and profile_is_complete( record ),
            'profile_updated' : record.updated_datetime if record is not None else None,
        }

    @staticmethod
    def _component_rename( request, flow ):
        """The Plans/Assumptions record this flow edits, as inline-rename fields for the header (kind, uuid,
        label, and its rename endpoint). None for the single-record Profile, which is not named."""
        if flow == 'plans':
            record, kind, route = current_plans_record( request ), 'plan', 'plans_rename'
        elif flow == 'assumptions':
            record, kind, route = current_assumptions_record( request ), 'assumptions', 'assumptions_rename'
        else:
            return None
        return { 'kind': kind, 'uuid': record.uuid, 'label': record.label,
                 'rename_url': reverse( route, kwargs = { 'uuid': record.uuid } ) }


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
    """`/inputs/interview/real-estate/residence/` -- the residence sub-form of the Real Estate pane. It
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
    single edit in the background: it persists the household (and the derived filing status), prunes any
    plan references orphaned when a partner is dropped, and refreshes the read-only filing-status readout
    beside the form, re-rendering the pane itself only on a genuine field error (a half-entered partner).
    Validation is non-blocking -- an incomplete person is simply not held; the forecast readiness check
    is the completeness gate."""

    _TEMPLATE        = 'inputs/interview/sections/subjects_pane.html'
    _ERRORS_TEMPLATE = 'inputs/interview/sections/subjects_errors.html'
    _FILING_STATUS   = 'filing-status'
    _ERRORS          = 'subjects-errors'

    def get( self, request ):
        profile, _plans = _current_profile_and_plans( request )
        return self._response( request, SubjectsForm( profile = profile ) )

    def post( self, request ):
        profile, plans = _current_profile_and_plans( request )
        form = SubjectsForm( request.POST, profile = profile )
        if not form.is_valid():
            return self._swap( request, form )                 # a half-entered partner
        # Dropping a partner removes their synced retirement/taxable accounts, so `apply` prunes the
        # plan references into them; profile and plans must then commit together (the paired-save seam).
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
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
    """`/inputs/interview/possessions/edit/` -- the list behind the Possessions section (tangible
    non-real-estate holdings). Its item set can change, so a save that adds or removes a row re-renders
    the pane; an incomplete row simply does not materialize."""

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


class ContributionsView( SelfSavingPaneView ):
    """`/inputs/interview/retirement/contributions/edit/` -- the recurring-contributions table of the
    Retirement section. Its row set can change, so a save that adds or removes a contribution re-renders
    the pane; a pure value edit stays silent. It writes only the Plans."""

    template     = 'inputs/interview/sections/contributions_pane.html'
    target       = 'contributions'
    context_name = 'contributions_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return ContributionsForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = len( plans.contributions )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )
        return len( plans.contributions ) != before            # a contribution was added or removed


class ConversionsView( SelfSavingPaneView ):
    """`/inputs/interview/tax-planning/conversions/edit/` -- the Roth conversions table of the Tax
    Planning section. Its row set can change, so a save that adds or removes a conversion re-renders the
    pane; a pure value edit stays silent. It writes only the Plans."""

    template     = 'inputs/interview/sections/conversions_pane.html'
    target       = 'conversions'
    context_name = 'conversions_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return ConversionsForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = len( plans.roth_conversions )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )
        return len( plans.roth_conversions ) != before         # a conversion was added or removed


class WithdrawalsView( SelfSavingPaneView ):
    """`/inputs/interview/tax-planning/withdrawals/edit/` -- the scheduled-withdrawals table of the Tax
    Planning section. Its row set can change, so a save that adds or removes a withdrawal re-renders the
    pane; a pure value edit stays silent. It writes only the Plans."""

    template     = 'inputs/interview/sections/withdrawals_pane.html'
    target       = 'withdrawals'
    context_name = 'withdrawals_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return WithdrawalsForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = len( plans.withdrawals )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )
        return len( plans.withdrawals ) != before              # a withdrawal was added or removed


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
    """`/inputs/interview/income/table/` -- the §5 income *facts* table. Its line set can change, so a
    save that adds or removes a line re-renders the pane; a pure value edit stays silent. It edits the
    Profile facts; the income timing is the separate Retirement (`RetirementView`) pane, save for reaping
    a removed flow's orphaned timing, so the pair is saved atomically."""

    template     = 'inputs/interview/sections/income_table.html'
    target       = 'income-table'
    context_name = 'income_form'

    def build_form( self, request, data = None ):
        profile, _plans = _current_profile_and_plans( request )
        return IncomeTableForm( data, profile = profile )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        before = self._line_count( profile )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )      # a removed flow reaps its orphaned timing
        return self._line_count( profile ) != before            # a line was added or removed

    @staticmethod
    def _line_count( profile ) -> int:
        """The general income lines (the only rows whose count changes); rental and entitlement rows
        are fixed by the properties and subjects."""
        return sum( 1 for flow in profile.income_flows if flow.property_handle is None )


class RetirementView( SelfSavingPaneView ):
    """`/inputs/interview/retirement/edit/` -- the income/entitlement *timing* of the Retirement section.
    It reads the income facts and entitlements from the Profile and persists only the Plans timing; the
    row set is fixed by the declared flows and subjects, so a half-entered window simply stores no
    timing. The age<->date sync is done client-side (`inputs.js`)."""

    template     = 'inputs/interview/sections/retirement_pane.html'
    target       = 'retirement'
    context_name = 'retirement_form'

    def build_form( self, request, data = None ):
        profile, plans = _current_profile_and_plans( request )
        return RetirementForm( data, profile = profile, plans = plans )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )


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
    """The add/edit form for one mortgaged property in the Real Estate pane. Add and edit converge:
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
    """`/inputs/interview/real-estate/rentals/add/` and `.../<handle>/`."""

    _PANE = RENTAL_PANE


class RentalDeleteView( _PropertyDeleteView ):
    """`/inputs/interview/real-estate/rentals/<handle>/delete/`."""

    _PANE = RENTAL_PANE


class SecondHomeFormView( _PropertyFormView ):
    """`/inputs/interview/real-estate/second-homes/add/` and `.../<handle>/`."""

    _PANE = SECOND_HOME_PANE


class SecondHomeDeleteView( _PropertyDeleteView ):
    """`/inputs/interview/real-estate/second-homes/<handle>/delete/`."""

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
        event_type = self._event_type( kind )
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'form': form, 'kind': kind, 'group': event_type.group, 'title': event_type.label,
              'description': event_type.description },
            request = request )

    def _list( self, request, profile, plans ):
        return render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) }, request = request )


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
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) }, request = request ) )
