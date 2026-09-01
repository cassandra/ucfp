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
from decimal import Decimal

from django import forms
from django.core.exceptions import BadRequest
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from organization.decorators import ensure_organization

from common import antinode
from common.exceptions import DataNotAvailableError
from common.async_view import ModalView
from common.request_utils import is_ajax

from ucfp.jurisdiction.government_pension import GovernmentPension

from ucfp.inputs.profile.repository import (
    advance_profile, create_profile, latest_profile, load_profile, save_profile )
from ucfp.inputs.plans.repository import (
    create_plans, latest_plans, load_plans, plans_for, rename_plans, save_plans )
from ucfp.inputs.assumptions.repository import (
    assumptions_for, create_assumptions, latest_assumptions, load_assumptions, rename_assumptions,
    save_assumptions )
from ucfp.inputs.scenarios.repository import (
    clone_scenario, create_fresh_scenario, create_scenario, default_scenario, delete_scenario,
    ensure_default_scenario, existing_pairings, rename_scenario, scenarios_for )
from ucfp.inputs import expense_totals
from ucfp.inputs.compatibility import (
    keep_home_rent, keep_loan_terms, plans_reconciled_with_profile, reset_home_rent, reset_loan_terms )
from ucfp.inputs.drift import plans_drift, plans_home_rent_drift, plans_loan_terms_drift
from ucfp.inputs.plans.enums import EventKind

from .interview import (
    Aggregate, AccountsForm, HomeForm, SubjectsForm, applicable_sections,
    first_section_of_flow, flow_of, flow_title, next_section_after, section_for )
from .enums import UsageRole
from .models import AssumptionsRecord, PlansRecord, ScenarioRecord
from .mixins import GuestReminderMixin, profile_refresh_required
from .state import (
    assumptions_completion_blockers, assumptions_is_complete, completed_assumptions, completed_plans,
    completed_profile, plans_completion_blockers, plans_is_complete, profile_advisories,
    profile_completion_blockers, profile_is_complete )
from .vehicle import VehicleForm, delete_vehicle, future_vehicle_heading, _minted_vehicle_handle
from .vehicle_disposition import (
    LeasedVehicleDispositionForm, VehicleDispositionForm, current_card_key, future_card_key,
    vehicle_plan_cards )
from .vehicle_expenses import VehicleExpensesForm
from .vehicle_profile import (
    CurrentVehicleForm, _minted_current_vehicle_handle, current_vehicles_context,
    delete_current_vehicle, vehicle_heading )
from .credit_card import CreditCardPlanForm
from .retirement_plans import ContributionsForm, ConversionsForm, WithdrawalsForm
from .external_factors import ExternalFactorsForm
from .cash_plan import DrawdownForm
from .net_worth import NetWorthForm
from .transaction_costs import TransactionCostsForm
from .debt_plan import DebtPlanForm
from .debts import DebtForm, _minted_debt_handle, debt_heading, debts_context, delete_debt
from .events import EventForm, events_context, handler_for, menu_context
from .income import IncomeTableForm
from .retirement_benefits import (
    RetirementBenefitsForm, SocialSecurityEstimatorForm, applied_government_benefit, subject_wage_total )
from .properties import (
    PossessionsForm, PropertyForm, _minted_handle, delete_property, properties_context,
    property_heading )
from .property_expenses import PropertyExpensesForm
from .recurring_expenses import RecurringExpensesForm
from .retirement import RetirementForm

_SCENARIOS_TEMPLATE = 'inputs/scenarios_home.html'
_SCENARIO_DELETE_CONFIRM_TEMPLATE = 'inputs/modals/scenario_delete_confirm.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenariosHomeView( View ):
    """`/inputs/scenarios/` -- "Manage Scenarios", the review/edit landing: the organization's saved
    scenarios as hero cards (each re-enters the whole Plans->Assumptions walk, with its components editable
    in place), plus one action to create another. Components have no standalone management -- they are born,
    edited, and retired through the scenarios that use them. Perspective-agnostic: it links to no planning
    perspective (forecast, retirement, ...) -- the main nav reaches those."""

    def get( self, request ):
        organization   = request.organization
        profile_record = completed_profile( organization )
        scenarios      = list( scenarios_for( organization ).select_related( 'plans', 'assumptions' ) )
        # Single-scenario shortcut: with a completed profile and exactly one scenario, reviewing/editing it
        # is the only useful action here, so enter it directly rather than showing a one-card list (the same
        # thing the card's "Review scenario" does). The list returns as soon as a second scenario exists;
        # + New scenario stays reachable from the edit page's header.
        if profile_record is not None and len( scenarios ) == 1:
            return _enter_scenario_build( request, scenarios[ 0 ] )
        # One pass over the saved scenarios drives the cards: per-component usage counts feed the "shared"
        # indicator, and the complete-component ids mark each scenario complete-vs-in-progress.
        plans_uses       = Counter( scenario.plans_id for scenario in scenarios )
        assumptions_uses = Counter( scenario.assumptions_id for scenario in scenarios )
        complete_ids     = self._complete_component_ids( organization, profile_record )
        profile          = load_profile( profile_record ) if profile_record is not None else None
        scenario_rows    = self._scenario_rows(
            scenarios, profile, plans_uses, assumptions_uses, *complete_ids )
        # The profile-freshness advisory: scenarios run off the profile, so note when it is from an earlier
        # month and link to its review (advisory here -- running is gated at the hub).
        refresh_required = profile_refresh_required( request )
        refresh_date     = latest_profile( organization ).effective_date if refresh_required else None
        return render( request, _SCENARIOS_TEMPLATE, {
            'active_nav'       : 'scenarios',
            # Building a scenario needs a completed profile first, so the page leads with the profile gate.
            'profile_complete' : profile_record is not None,
            'scenarios'        : scenario_rows,
            # A household keeps at least one scenario, so its sole scenario's delete control is suppressed.
            'can_delete_scenario' : len( scenarios ) > 1,
            'profile_refresh_required'       : refresh_required,
            'profile_refresh_effective_date' : refresh_date,
        } )

    @staticmethod
    def _complete_component_ids( organization, profile_record ):
        """The ids of the org's complete Plans and Assumptions, so a scenario counts complete when both of
        its components' flows are walked. No profile means nothing is complete (the profile gate shows)."""
        if profile_record is None:
            return ( set(), set() )
        return ( { record.id for record in completed_plans( profile_record, organization ) },
                 { record.id for record in completed_assumptions( profile_record, organization ) } )

    @staticmethod
    def _scenario_rows( scenarios, profile, plans_uses, assumptions_uses, plans_ids, assumptions_ids ):
        """Each saved scenario as a row -- `complete` (both components complete), `blockers` (the per-input
        requirements a *finished* scenario still lacks; non-empty only when finished-but-blocked, so the card
        tells that apart from a still-unfinished one and can name the reasons), its `drift` notice against the
        current `profile` (None when it fully resolves, else the stale references + reconcile shown on the
        card), and how many scenarios share each of its components (`plans_uses` / `assumptions_uses`) for the
        "shared" indicator. `scenarios` and the usage counters are prepared once by the caller so the page
        makes a single scenarios query."""
        rows = list()
        for scenario in scenarios:
            complete = scenario.plans_id in plans_ids and scenario.assumptions_id in assumptions_ids
            blockers = ( plans_completion_blockers( profile, scenario.plans )
                         + assumptions_completion_blockers( profile, scenario.assumptions )
                         if profile is not None else list() )
            rows.append( { 'scenario': scenario, 'complete': complete, 'blockers': blockers,
                           'drift': plans_drift( profile, scenario.plans ) if profile is not None else None,
                           'loan_terms_drift': ( plans_loan_terms_drift( profile, scenario.plans )
                                                 if profile is not None else None ),
                           'home_rent_drift': ( plans_home_rent_drift( profile, scenario.plans )
                                                if profile is not None else None ),
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
        label = 'Plans', choices = _MODE_CHOICES, initial = 'copy',
        widget = forms.RadioSelect( attrs = { 'class': 'form-check-input' } ) )
    assumptions_mode = forms.ChoiceField(
        label = 'Assumptions', choices = _MODE_CHOICES, initial = 'copy',
        widget = forms.RadioSelect( attrs = { 'class': 'form-check-input' } ) )

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


class StartFreshForm( _NamedScenarioForm ):
    """Start a brand-new scenario from scratch. The name is optional -- blank takes the auto-numbered
    default -- but if given it goes through the same strip / length / duplicate checks as the other
    creation paths, so all three share one name-validation authority."""

    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        self.fields[ 'name' ].required = False


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
        form = StartFreshForm(
            request.POST, prefix = 'fresh', taken_names = self._taken_names( request.organization ) )
        if not form.is_valid():
            return render(
                request, self._TEMPLATE,
                self._context( request.organization, profile_record, fresh_form = form ) )
        scenario = create_fresh_scenario( request.organization, form.cleaned_data[ 'name' ] or None )
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

    def _context( self, organization, profile_record,
                  copy_form = None, pair_form = None, fresh_form = None ):
        # Compute the completeness sets once and split the scenarios in a single pass (the completeness
        # scan is the page's heaviest work, so the paths below all derive from these rather than re-scan).
        plans, assumptions = self._complete_components( organization, profile_record )
        complete_scenarios, incomplete_scenarios = self._split_scenarios( organization, plans, assumptions )
        available          = self._available_assumptions( organization, plans, assumptions )
        taken_names        = self._taken_names( organization )
        pairable_plans     = [ record for record in plans if available[ str( record.uuid ) ] ]
        return {
            'active_nav'            : 'scenarios',
            'has_complete_scenario' : bool( complete_scenarios ),
            'incomplete_scenarios'  : incomplete_scenarios,
            'can_pair'              : bool( pairable_plans ),
            'pair_form'             : pair_form or PairScenarioForm(
                prefix = 'pair', plans = pairable_plans, assumptions = assumptions,
                taken = existing_pairings( organization ), taken_names = taken_names ),
            'copy_form'             : copy_form or CopyScenarioForm(
                prefix = 'copy', scenarios = complete_scenarios, taken_names = taken_names ),
            'fresh_form'            : fresh_form or StartFreshForm( prefix = 'fresh', taken_names = taken_names ),
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

    @staticmethod
    def _split_scenarios( organization, complete_plans_records, complete_assumptions_records ):
        """The organization's saved scenarios partitioned into (complete, in-progress): a scenario is
        complete when both its components' flows are walked. Complete ones a Copy can start from;
        in-progress ones are surfaced so the user sees why their components are not available to pair."""
        plan_ids       = { record.id for record in complete_plans_records }
        assumption_ids = { record.id for record in complete_assumptions_records }
        complete, in_progress = list(), list()
        for scenario in scenarios_for( organization ).select_related( 'plans', 'assumptions' ):
            bucket = ( complete if scenario.plans_id in plan_ids and scenario.assumptions_id in assumption_ids
                       else in_progress )
            bucket.append( scenario )
        return ( complete, in_progress )

    def _complete_scenarios( self, organization, profile_record ):
        """The saved scenarios a Copy can start from -- both components complete."""
        plans, assumptions = self._complete_components( organization, profile_record )
        return self._split_scenarios( organization, plans, assumptions )[ 0 ]

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
class ScenarioDeleteConfirmView( ModalView ):
    """`/inputs/scenarios/<uuid>/delete-confirm/` -- the styled confirm dialog the Scenarios page opens
    before deleting a scenario. Its Delete action posts to `scenario_delete`."""

    def get_template_name( self ):
        return _SCENARIO_DELETE_CONFIRM_TEMPLATE

    def get( self, request, uuid ):
        record = get_object_or_404(
            ScenarioRecord, uuid = uuid, organization = request.organization, usage_role = UsageRole.SAVED )
        return self.modal_response( request, context = { 'scenario': record } )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansReconcileView( View ):
    """`/inputs/plans/<uuid>/reconcile/` -- strip a Plans record's references that no longer resolve
    against the current Profile (the "Remove stale references" fix every drift surface offers). Plans, not
    scenarios, carry the Profile dependencies, so this is the *core* reconcile -- one fix that serves every
    scenario sharing these Plans. POST, since it edits the Plans; returns to the page it was triggered from.
    No-op when there is no complete profile to reconcile against (nothing would resolve)."""

    def post( self, request, uuid ):
        plans_record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _reconcile_plans_record( request.organization, plans_record )
        return _reconcile_redirect( request )


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioReconcileView( View ):
    """`/inputs/scenarios/<uuid>/reconcile/` -- reconcile a scenario by its Plans: the scenario-keyed thin
    wrapper over `PlansReconcileView`, dereferencing the scenario to its Plans record and reconciling that.
    POST; returns to the page it was triggered from."""

    def post( self, request, uuid ):
        scenario = get_object_or_404(
            ScenarioRecord, uuid = uuid, organization = request.organization, usage_role = UsageRole.SAVED )
        _reconcile_plans_record( request.organization, scenario.plans )
        return _reconcile_redirect( request )


def _reconcile_plans_record( organization, plans_record ):
    """Strip `plans_record`'s references that no longer resolve against the org's current profile -- the
    core both reconcile views share. A no-op when there is no complete profile (reconciling against nothing
    would strip everything)."""
    profile_record = completed_profile( organization )
    if profile_record is not None:
        save_plans( plans_record, plans_reconciled_with_profile(
            load_profile( profile_record ), load_plans( plans_record ) ) )


def _reconcile_redirect( request ):
    """Back to the page the reconcile was triggered from -- the forecast hub, a Scenarios card, or a Plans
    section -- re-rendered without the stale references; the Scenarios home is the fallback when the
    referer is missing or off-site."""
    referer = request.META.get( 'HTTP_REFERER' )
    if referer and url_has_allowed_host_and_scheme( referer, allowed_hosts = { request.get_host() } ):
        return redirect( referer )
    return redirect( 'scenarios_home' )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansLoanTermsResetView( View ):
    """`/inputs/plans/<uuid>/loan-terms/<handle>/reset/` -- adopt the updated Profile contract for one loan,
    re-seeding this Plans record's repayment from it and refreshing the drift snapshot. POST; returns to the
    page it was triggered from. The value-drift twin of `PlansReconcileView`, one loan at a time."""

    def post( self, request, uuid, handle ):
        _resolve_loan_terms_drift( request, uuid, handle, reset_loan_terms )
        return _reconcile_redirect( request )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansLoanTermsKeepView( View ):
    """`/inputs/plans/<uuid>/loan-terms/<handle>/keep/` -- keep this Plans record's repayment for one loan
    and refresh the drift snapshot to the current contract, so the drift clears without changing the plan.
    POST; returns to the page it was triggered from."""

    def post( self, request, uuid, handle ):
        _resolve_loan_terms_drift( request, uuid, handle, keep_loan_terms )
        return _reconcile_redirect( request )


def _resolve_loan_terms_drift( request, uuid, handle, choose ):
    """Apply a per-loan drift choice (`reset_loan_terms` or `keep_loan_terms`) to the named Plans record --
    the core both loan-terms drift views share. A no-op when there is no complete profile to reconcile
    against (there would be no current contract to compare)."""
    plans_record   = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
    profile_record = completed_profile( request.organization )
    if profile_record is not None:
        save_plans( plans_record, choose(
            load_profile( profile_record ), load_plans( plans_record ), handle ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansHomeRentResetView( View ):
    """`/inputs/plans/<uuid>/home-rent/reset/` -- adopt the updated Profile rent for this Plans record,
    re-seeding its rented-home rent expense and refreshing the drift snapshot. POST; returns to the page it
    was triggered from. The single-value twin of `PlansLoanTermsResetView`."""

    def post( self, request, uuid ):
        _resolve_home_rent_drift( request, uuid, reset_home_rent )
        return _reconcile_redirect( request )


@method_decorator( ensure_organization, name = 'dispatch' )
class PlansHomeRentKeepView( View ):
    """`/inputs/plans/<uuid>/home-rent/keep/` -- keep this Plans record's rent and refresh the drift
    snapshot to the current Profile rent, so the drift clears without changing the plan. POST; returns to
    the page it was triggered from."""

    def post( self, request, uuid ):
        _resolve_home_rent_drift( request, uuid, keep_home_rent )
        return _reconcile_redirect( request )


def _resolve_home_rent_drift( request, uuid, choose ):
    """Apply a rent drift choice (`reset_home_rent` or `keep_home_rent`) to the named Plans record -- the
    core both home-rent drift views share. A no-op when there is no complete profile to reconcile against."""
    plans_record   = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
    profile_record = completed_profile( request.organization )
    if profile_record is not None:
        save_plans( plans_record, choose(
            load_profile( profile_record ), load_plans( plans_record ) ) )


@method_decorator( ensure_organization, name = 'dispatch' )
class FlowEntryView( View ):
    """`/inputs/<flow>/` -- edit a single input flow (Profile, Plans, or Assumptions) on its own. `flow`
    is set per route via `as_view`. Profile is the standalone first flow; Plans/Assumptions are edited on
    their own here (and, in the scenario-building flow, chained -- see `InterviewView`).

    Entering the Profile flow binds the Profile to the organization's Default scenario: it ensures a
    Default Plans + Assumptions + Scenario exist and makes those components the editing target, so the
    profile's straddle sections (Property, Income) write their shared, profile-derived data into the
    Default's Plans rather than minting a stray one."""

    _REFRESH_TEMPLATE = 'inputs/profile_refresh.html'

    flow = None

    def get( self, request ):
        # An aged profile is refreshed by an explicit, acknowledged advance -- so entering the Profile flow
        # with an outdated snapshot lands on the review prompt instead of the editor, keeping the user off
        # the stale-dated record until they advance it (Plans/Assumptions are advisory-only, so they fall
        # through).
        if self.flow == 'profile' and profile_refresh_required( request ):
            # `profile_refresh_required` already established a complete (hence present) latest profile.
            return render( request, self._REFRESH_TEMPLATE,
                           { 'profile_updated': latest_profile( request.organization ).effective_date } )
        # A standalone flow is not a scenario build. Clear any build scope left over from an abandoned
        # build, so a lone Plans edit does not wrongly chain into Assumptions (nor show the build
        # breadcrumb, nor finish on the Scenarios page). The scenario build enters through
        # `ScenarioEditView`, which sets the scope -- never through here.
        request.session_state.editing_scenario = None
        request.session_state.to_session( request )
        if self.flow == 'profile':
            # Entering the Profile flow sets the household up (its Default Plans/Assumptions/Scenario, and
            # the empty initial Profile). A read-only member cannot write, so on a household never set up
            # by a writer this would fail with a generic authorization error; say plainly there is no data
            # yet instead. (A near-edge case: a household a writer never touched.)
            if ( not request.organization_can_write ) and default_scenario( request.organization ) is None:
                raise DataNotAvailableError( 'This household has no Profile data set up yet.' )
            default = ensure_default_scenario( request.organization )
            _select( request, 'current_plans_uuid', default.plans )
            _select( request, 'current_assumptions_uuid', default.assumptions )
        first = first_section_of_flow( self.flow )
        if first is None:
            raise Http404( f'No sections in flow {self.flow!r}.' )
        return redirect( 'interview_section', section = first.key )

    def post( self, request ):
        """Acknowledge the review prompt: advance the profile into the current month (carrying the facts
        forward, reopening the volatile sections) and re-enter the Profile flow -- now current-dated, so
        `get` walks the refreshed snapshot. Only the Profile flow prompts; a stray POST elsewhere 404s.
        Idempotent via `advance_profile`, so a double submit does not duplicate the month."""
        if self.flow != 'profile':
            raise Http404( f'Flow {self.flow!r} has no review prompt to acknowledge.' )
        if profile_refresh_required( request ):            # advance only a complete, outdated profile;
            advance_profile( request.organization )        # an in-progress one is never copied
        return redirect( 'flow_profile' )


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
class PlansEditView( View ):
    """`/inputs/plans/<uuid>/edit/` -- edit an existing Plans component (Edit-component): make it the
    current editing target and open the standalone Plans flow on it."""

    def get( self, request, uuid ):
        record = get_object_or_404( PlansRecord, uuid = uuid, organization = request.organization )
        _select( request, 'current_plans_uuid', record )
        return redirect( 'flow_plans' )


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
class InterviewView( GuestReminderMixin, View ):
    """`/inputs/interview/<section>/` -- one section of the interview: an antinode-swapped
    linear flow over the organization's current Profile, Plans, and Assumptions. A full GET renders
    the whole page; an async GET (a stepper revisit) or a POST swaps just the section pane and
    refreshes the stepper.

    On a valid POST the section is saved and the *next* section is recomputed from the now-updated
    profile -- the conditional-flow payoff. Each section merges only its own part via `apply`,
    so advancing (or revisiting) never clobbers another section's facts.
    """

    # Profile is a top-level page, a scenario component (Plans/Assumptions) a detail page; they share the
    # stepping body but not the header, so each flow renders its own thin page over the shared layouts.
    _PROFILE_TEMPLATE   = 'inputs/interview/profile_page.html'
    _COMPONENT_TEMPLATE = 'inputs/interview/component_page.html'
    _SECTION_TEMPLATE = 'inputs/interview/section.html'
    _STEPPER_TEMPLATE = 'inputs/interview/stepper.html'
    # The route this interview is hosted at -- the single source of truth every navigation URL (the stepper
    # and Next links, the async push_url, and the read-only Finish) derives from. A subclass that hosts the
    # same interview elsewhere (the example-data tour) overrides just this, and all its navigation follows.
    SECTION_URL_NAME  = 'interview_section'
    # The status shows in two swap targets: the rail header (the completion badge, plus the Plans/Assumptions
    # part switch in a scenario build) and the detail notices below the page heading. Both refresh on advance,
    # so the active part's badge and its blocker alert update together without a reload.
    _RAIL_TEMPLATE   = 'inputs/interview/rail_header.html'
    _DETAIL_TEMPLATE = 'inputs/interview/interview_status_detail.html'
    _SECTION_TARGET   = 'interview-section'
    _STEPPER_TARGET   = 'interview-stepper'
    _RAIL_TARGET      = 'interview-rail-header'
    _DETAIL_TARGET    = 'interview-status-detail'

    def get( self, request, section ):
        current  = self._live_section( section )
        # A profile section must not be walked while the snapshot is outdated: presenting it would
        # acknowledge it against the prior month's (immutable) record. Route to the Profile page's review
        # prompt, which advances first. Plans/Assumptions sections fall through -- they carry only the
        # advisory banner (below), never a block.
        if flow_of( current ) == 'profile' and profile_refresh_required( request ):
            return redirect( 'flow_profile' )
        self._seed_and_acknowledge( request, current )         # presenting the section is the acknowledgment
        profile, other = self._load( request, current )
        sections = self._flow_sections( profile, flow_of( current ) )
        form     = self._form( current, profile, other )
        if is_ajax( request ):
            return self._swap( request, sections, current, form )
        return render(
            request, self._page_template( current ), self._context( request, sections, current, form ) )

    def _page_template( self, section ):
        """The full-page template for `section`'s flow -- Profile is a top-level page, Plans/Assumptions
        detail pages. The explicit, overridable seam by which a wrapper (the example-data tour) renders the
        same interview under a different shell."""
        return self._PROFILE_TEMPLATE if flow_of( section ) == 'profile' else self._COMPONENT_TEMPLATE

    def _seed_and_acknowledge( self, request, section ):
        """Presenting a section to the user is the acknowledgment that they have seen it. On the first
        view a *seeding* section (one whose `apply` is a pure catalog merge) also persists its defaults,
        so what the user sees is already saved (matching the auto-save spirit) and an acknowledged spending
        section is never empty. Both happen only here -- the merge builders are never a source of
        acknowledgment on their own -- and only on first view, so revisits are inert.

        Both are data writes that ride a GET, so they are skipped for a read-only member: the HTTP-method
        write-gate cannot see them, and a viewer must not mutate the household just by browsing it."""
        if not getattr( request, 'organization_can_write', True ):
            return
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
        return latest_profile( request.organization ) or _mint_profile( request )

    def post( self, request, section ):
        current = self._live_section( section )
        flow = flow_of( current )
        profile, other = self._load( request, current )
        form = self._form( current, profile, other, request.POST )
        if not form.is_valid():
            return self._swap( request, self._flow_sections( profile, flow ), current, form )
        profile   = self._store( request, current, form, profile, other )
        following = self._following_section(
            request, self._flow_sections( profile, flow ), current.key, flow )
        if following is None:                                   # nothing more to present -- this flow ends
            building     = request.session_state.editing_scenario
            destination  = self._completion_destination( request, flow, building )
            if building:                                        # the two-part build is done: clear its marker
                request.session_state.editing_scenario = None
                request.session_state.to_session( request )
            return antinode.redirect_response( destination )
        self._seed_and_acknowledge( request, following )       # the advanced-to section is now presented
        next_sections = self._flow_sections( profile, flow_of( following ) )
        next_profile, next_other = self._load( request, following )
        next_form = self._form( following, next_profile, next_other )
        return self._swap( request, next_sections, following, next_form )

    @staticmethod
    def _following_section( request, sections, section_key, flow ):
        """The section the flow advances to after `section_key`: the next in-flow section, or -- when a
        whole scenario is being edited (a build), not Plans alone -- the first Assumptions section once
        Plans ends. None means the flow finishes here. Shared by the advance POST, the read-only 'Next',
        and `is_last`, so all agree on whether the last Plans step chains into Assumptions or finishes."""
        following = next_section_after( sections, section_key )
        if ( following is None ) and request.session_state.editing_scenario and ( flow == 'plans' ):
            following = first_section_of_flow( 'assumptions' )  # scenario build: chain Plans -> Assumptions
        return following

    def _completion_destination( self, request, flow, building ) -> 'str | None':
        """Where a completed flow lands -- a pure URL (the advance POST finalizes the build itself). A
        scenario build (Plans then Assumptions) finishes at the end of Assumptions on the Scenarios page.
        Finishing the standalone Profile loops back to its first section (via `SECTION_URL_NAME`, so the tour
        stays in the tour), where the header now shows it is complete; a standalone component edit likewise
        ends on the Scenarios page. Features are reached from the nav, so no flow threads a return
        destination."""
        if building:                                           # end of the two-part build (Assumptions done)
            return reverse( 'scenarios_home' )
        if flow == 'profile':
            first = first_section_of_flow( 'profile' )
            return reverse( self.SECTION_URL_NAME, kwargs = { 'section': first.key } )
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
        profile_record = latest_profile( organization ) or _mint_profile( request )
        profile = load_profile( profile_record )
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
        # Refresh the stepper's seen-marks, the rail header (the completion badge / part switch), and the
        # detail notices alongside the section, so advancing reflects the now-updated flow at once -- e.g.
        # adding the missing person clears the incomplete state without a reload. The detail is empty (a
        # no-op replace) for a flow with no notice to show.
        return antinode.response(
            main_content = render_to_string( self._SECTION_TEMPLATE, context, request = request ),
            replace_map = {
                self._STEPPER_TARGET     : render_to_string( self._STEPPER_TEMPLATE, context, request = request ),
                self._RAIL_TARGET        : render_to_string( self._RAIL_TEMPLATE, context, request = request ),
                self._DETAIL_TARGET      : render_to_string( self._DETAIL_TEMPLATE, context, request = request ),
                # Always refreshed (content or empty), like the detail: it must clear if the profile is
                # edited back to incomplete, or the flow is no longer complete (GuestReminderMixin decides).
                self.GUEST_BANNER_TARGET : render_to_string( self.GUEST_BANNER_TEMPLATE, context, request = request ),
            },
            push_url = reverse( self.SECTION_URL_NAME, kwargs = { 'section': section.key } ),
            scroll_to = self._SECTION_TARGET )

    def _context( self, request, sections, section, form ):
        flow = flow_of( section )
        rail = self._rail_header( request, flow )
        following = self._following_section( request, sections, section.key, flow )
        context = {
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
            # The scenario being built, as an inline rename -- so its name is editable here (the page's
            # identity in a build); None outside a build, where the component name is the identity instead.
            'scenario_rename'      : self._scenario_rename( request ),
            # The component being edited, as an inline rename in the header, so its name can be changed
            # here (e.g. straight after a create or clone) rather than only on the Scenarios page.
            'component_rename'     : self._component_rename( request, flow ),
            # The last step of the flow context shows "Finish" rather than "Next" (in a build, the last
            # Plans step chains into Assumptions, so it is not the finish).
            # `following` is where the flow advances to (None on the final step) -- shared with the POST
            # so the read-only "Next" and the editable advance always agree. It drives the editable
            # Finish/Next label, and in read-only mode is the plain-navigation "Next" target (a sequential
            # reader) in place of the advance-and-save button.
            'is_last'              : following is None,
            'next_section'         : following,
            # Where the flow's last step leads, so a read-only member's "Finish" navigates out of the flow
            # (the same place the advance-and-save Finish lands) rather than saving.
            'completion_destination': self._completion_destination(
                request, flow, request.session_state.editing_scenario ),
            'form'                 : form,
            'section_target'       : self._SECTION_TARGET,
            'stepper_target'       : self._STEPPER_TARGET,
            # The route the stepper/Next links point at (see the `SECTION_URL_NAME` class attribute).
            'section_url_name'     : self.SECTION_URL_NAME,
            # The Plans-flow drift banner: these plans reference removed Profile entities (None off Plans).
            'drift'                : self._plans_drift( request, flow ),
            # The sibling loan-terms drift banner: a loan's contract terms changed since the plan seeded.
            'loan_terms_drift'     : self._plans_loan_terms_drift( request, flow ),
            # The sibling home-rent drift banner: the Profile rent changed since the plan's rent seeded.
            'home_rent_drift'      : self._plans_home_rent_drift( request, flow ),
            # The profile-freshness advisory banner for a Plans/Assumptions page (see the method).
            **self._profile_refresh_notice( request, flow ),
            # The rail header: the completion badge(s) and, in a build, the Plans/Assumptions part switch.
            **rail,
            # The current flow's blocker/advisory notices for the detail banner below the heading.
            **self._profile_status( request, flow ),
            **self._plans_status( request, flow ),
            **self._assumptions_status( request, flow ),
        }
        # Whether the current flow is complete -- the one signal GuestReminderMixin can't derive itself
        # (it alone reads the rail). The mixin owns the rest of the "should the reminder show" decision,
        # incl. keeping it clear mid-build so it never competes with an incompleteness message.
        current_flow_complete = any( part[ 'active' ] and part[ 'status' ] == 'complete'
                                     for part in rail[ 'rail_parts' ] )
        context[ 'show_guest_email_banner' ] = self.show_guest_reminder( request, current_flow_complete )
        context['current_flow_complete'] = current_flow_complete
        return context

    @staticmethod
    def _profile_refresh_notice( request, flow ) -> dict:
        """The profile-freshness advisory for a component flow -- whether the shared profile is outdated and
        the month it is from, for the Plans/Assumptions advisory banner. Empty on the profile flow (which is
        redirected to its review prompt instead) so the banner never competes with the prompt."""
        if flow == 'profile' or not profile_refresh_required( request ):
            return { 'profile_refresh_required': False }
        latest = latest_profile( request.organization )
        return { 'profile_refresh_required': True,
                 'profile_refresh_effective_date': latest.effective_date if latest is not None else None }

    @staticmethod
    def _plans_drift( request, flow ):
        """The current Plans record's drift notice for the Plans-flow banner (stale Profile references +
        the one-click reconcile), or None off the Plans flow (only Plans reference the Profile) or before a
        *complete* profile exists to judge against. Gated on `completed_profile` (not merely the latest),
        matching the reconcile action -- so the banner never shows a fix that would no-op, and an
        incomplete profile can't read as false drift."""
        if flow != 'plans':
            return None
        profile_record = completed_profile( request.organization )
        if profile_record is None:
            return None
        return plans_drift( load_profile( profile_record ), current_plans_record( request ) )

    @staticmethod
    def _plans_loan_terms_drift( request, flow ):
        """The current Plans record's loan-terms drift notice for the Plans-flow banner (loans whose
        contract terms changed since the plan seeded from them + the per-loan reset/keep), or None off the
        Plans flow or before a *complete* profile exists (so the banner never shows a fix that would
        no-op)."""
        if flow != 'plans':
            return None
        profile_record = completed_profile( request.organization )
        if profile_record is None:
            return None
        return plans_loan_terms_drift( load_profile( profile_record ), current_plans_record( request ) )

    @staticmethod
    def _plans_home_rent_drift( request, flow ):
        """The current Plans record's home-rent drift notice for the Plans-flow banner (the Profile rent
        changed since the plan's rent expense seeded from it + the update/keep), or None off the Plans flow
        or before a *complete* profile exists (so the banner never shows a fix that would no-op)."""
        if flow != 'plans':
            return None
        profile_record = completed_profile( request.organization )
        if profile_record is None:
            return None
        return plans_home_rent_drift( load_profile( profile_record ), current_plans_record( request ) )

    def _rail_header( self, request, flow ) -> dict:
        """The stepper's header context: the flow's title and completion badge. In a scenario build (editing
        a scenario's Plans/Assumptions) it is a two-part switch -- both parts, each with its own status, the
        inactive one linking to its first section -- so the user can move between Plans and Assumptions in
        either direction. Otherwise (an individual component edit, or the Profile) it is the single active
        flow. The badge lives here, the one home for status across every interview."""
        profile_record = latest_profile( request.organization )
        profile        = load_profile( profile_record ) if profile_record is not None else None
        scenario_mode  = bool( request.session_state.editing_scenario ) and flow in ( 'plans', 'assumptions' )
        parts          = [ 'plans', 'assumptions' ] if scenario_mode else [ flow ]
        entries = [ { 'label' : flow_title( part ),
                      'status': self._part_status( request, profile, part ),
                      'url'   : reverse( self.SECTION_URL_NAME,
                                         kwargs = { 'section': first_section_of_flow( part ).key } ),
                      'active': part == flow }
                    for part in parts ]
        return { 'rail_parts': entries, 'rail_scenario_mode': scenario_mode }

    @staticmethod
    def _part_status( request, profile, flow ) -> str:
        """A flow's completion state for its rail badge: 'complete', 'blocked' (every section walked but a
        hard requirement is still unmet), or 'in_progress' (still being walked, or nothing to judge yet).
        Reads the flow's current record; the blockers are non-empty only once the flow is walked, so a
        blocked state cannot show mid-walk."""
        if flow == 'profile':
            record = latest_profile( request.organization )
            if record is None:
                return 'in_progress'
            if profile_is_complete( record ):
                return 'complete'
            return 'blocked' if profile_completion_blockers( record ) else 'in_progress'
        if flow == 'plans':
            record = current_plans_record( request )
            if profile is None or record is None:
                return 'in_progress'
            if plans_is_complete( profile, record ):
                return 'complete'
            return 'blocked' if plans_completion_blockers( profile, record ) else 'in_progress'
        record = current_assumptions_record( request )
        if profile is None or record is None:
            return 'in_progress'
        if assumptions_is_complete( profile, record ):
            return 'complete'
        return 'blocked' if assumptions_completion_blockers( profile, record ) else 'in_progress'

    @staticmethod
    def _profile_status( request, flow ) -> dict:
        """The Profile flow's detail notices -- the snapshot's as-of month, the blocker reasons (once walked),
        and the advisories (once complete). Empty for the component flows. The completion badge is the rail
        header's; this feeds only the detail banner below the heading."""
        if flow != 'profile':
            return dict()
        record = latest_profile( request.organization )
        return {
            # The snapshot's *effective* month (its "as of"), not the row's auto-updated timestamp: the facts
            # hold as of this month, which is what a re-run and the freshness check both key on.
            'profile_updated' : record.effective_date if record is not None else None,
            # Non-empty only once every section is walked but the profile is still incomplete -- the reasons
            # to show then, in the danger detail banner.
            'profile_blockers': profile_completion_blockers( record ) if record is not None else [],
            # Quiet, non-blocking notes for a complete profile (e.g. no funded account) -- an FYI, not an
            # error; only surfaced once complete, so never alongside a blocker.
            'profile_advisories': profile_advisories( record ) if record is not None else [],
        }

    @staticmethod
    def _plans_status( request, flow ) -> dict:
        """The Plans flow's detail notices -- once walked, the hard requirements it still lacks (an amortizing
        debt with no repayment plan) for the danger banner. Empty for the other flows."""
        if flow != 'plans':
            return dict()
        profile_record = latest_profile( request.organization )
        record         = current_plans_record( request )
        if profile_record is None or record is None:
            return { 'plans_blockers': [] }
        return { 'plans_blockers': plans_completion_blockers( load_profile( profile_record ), record ) }

    @staticmethod
    def _assumptions_status( request, flow ) -> dict:
        """The Assumptions flow's detail notices -- once walked, the hard requirements it still lacks (the
        external factors) for the danger banner. Empty for the other flows."""
        if flow != 'assumptions':
            return dict()
        profile_record = latest_profile( request.organization )
        record         = current_assumptions_record( request )
        if profile_record is None or record is None:
            return { 'assumptions_blockers': [] }
        return { 'assumptions_blockers':
                 assumptions_completion_blockers( load_profile( profile_record ), record ) }

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

    @staticmethod
    def _scenario_rename( request ):
        """The scenario being built, as inline-rename fields for the page heading -- so its name is editable
        right on the interview (its identity during a build), like the components are on their own pages.
        None outside a build."""
        uuid = request.session_state.editing_scenario
        if uuid is None:
            return None
        record = ScenarioRecord.objects.filter( uuid = uuid, organization = request.organization ).first()
        if record is None:
            return None
        return { 'kind': 'scenario', 'uuid': record.uuid, 'label': record.label,
                 'rename_url': reverse( 'scenario_rename', kwargs = { 'uuid': record.uuid } ) }


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
        # Silent background save: leave the edited pane untouched, but push any on-page totals the edit
        # moved (empty for panes without totals -- an empty map is `antinode.response()` unchanged).
        return antinode.response( replace_map = self.totals_fragments( request ) or None )

    def build_form( self, request, data = None ):
        raise NotImplementedError

    def persist( self, request, form ):
        raise NotImplementedError

    def totals_fragments( self, request ) -> dict:
        """Id-keyed HTML fragments re-rendering the pane's live totals after a silent save, for an
        antinode `replace_map`. Empty by default (most panes show no totals); a totals-bearing pane
        mixes in `TotalsPaneMixin` to recompute from the just-persisted plans."""
        return dict()

    def _pane( self, request, form ) -> str:
        return render_to_string( self.template, { self.context_name: form }, request = request )

    def _swap( self, request, form ):
        # Replace the pane by id (not a data-async target) so the loader-suppressed background POST,
        # which carries no target, still applies the re-render.
        return antinode.response( replace_map = { self.target: self._pane( request, form ) } )


class TotalsPaneMixin:
    """A self-saving pane that shows server-computed expense totals. After a silent save it recomputes
    the totals from the just-persisted plans -- a fresh form, so the figures reflect the edit -- and
    pushes each as its own antinode replace fragment, leaving the edited row undisturbed. The pane's
    form exposes the totals as a `totals` list of `ExpenseTotal`s."""

    def totals_fragments( self, request ) -> dict:
        return expense_totals.rendered( request, self.build_form( request ).totals )


@method_decorator( ensure_organization, name = 'dispatch' )
class _VehicleListView( View ):
    """Shared, org-scoped base for the Vehicle plan's one list -- the household's current vehicles then any
    net-new future ones. The per-vehicle add/edit/delete swaps (and the disposition editors) refresh this
    one list; the per-car running costs are the sibling `VehicleExpensesView` pane."""

    _LIST_TEMPLATE = 'inputs/interview/sections/vehicle_plan_list.html'

    def _list( self, request, profile, plans, active = None ):
        return render_to_string(
            self._LIST_TEMPLATE,
            { 'cards': vehicle_plan_cards( profile, plans ), 'active': active },
            request = request )


class VehicleFormView( _VehicleListView ):
    """`/inputs/interview/vehicle-expenses/vehicles/add/` and `.../<handle>/` -- the add/edit form for
    one vehicle. Add and edit converge on a minted handle, so a new vehicle has a stable identity from
    the first keystroke. POST background-saves (non-blocking, so an incomplete vehicle writes nothing)
    and refreshes the list; the open form is left untouched except to surface a genuine field error."""

    _FORM_TEMPLATE = 'inputs/interview/sections/vehicle_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):                  # Done: restore the slot's resting state
            return antinode.response(
                main_content = self._form( request, None, None, plans ),
                replace_map  = { 'vehicle-plan-list': self._list( request, profile, plans ) } )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_vehicle_handle( plans )
        form = VehicleForm( profile = profile, plans = plans, handle = handle )
        return antinode.response(
            main_content = self._form( request, handle, form, plans ),
            replace_map  = { 'vehicle-plan-list':
                             self._list( request, profile, plans, future_card_key( handle ) ) } )

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = VehicleForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'vehicle-editor': self._form( request, handle, form, plans ) } )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response(
            replace_map = { 'vehicle-plan-list':
                            self._list( request, profile, plans, future_card_key( handle ) ) } )

    def _form( self, request, handle, form, plans ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'vehicle_form': form, 'handle': handle, 'heading': future_vehicle_heading( plans, handle ) },
            request = request )


class VehicleDeleteView( _VehicleListView ):
    """`.../vehicle-expenses/vehicles/<handle>/delete/` -- remove one vehicle, then refresh the list."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        plans = delete_vehicle( plans, handle )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response(
            replace_map = { 'vehicle-plan-list': self._list( request, profile, plans ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class _VehicleDispositionView( View ):
    """The disposition editor for one current vehicle, opened into the single shared list + form area.
    GET opens the editor for the handle (or, with `?collapse`, empties the editor area); POST background-
    saves the disposition (non-blocking) and refreshes the one current-vehicles list. Edit-only: the rows
    are the current vehicles, so there is no add or delete. Subclasses supply the form class, its editor
    template, and the template's context key for the form -- the owned (Retain/Sell/Replace) and leased
    (Return/Renew/Buy) editors are otherwise identical."""

    _LIST_TEMPLATE    = 'inputs/interview/sections/vehicle_plan_list.html'
    _FORM_TEMPLATE    = None    # subclass: its editor template
    _form_class       = None    # subclass: its disposition form
    _form_context_key = None    # subclass: the template's key for the form

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):                  # Done: restore the slot's resting state
            return antinode.response(
                main_content = self._form( request, None, None, profile ),
                replace_map  = { 'vehicle-plan-list': self._list( request, profile, plans ) } )
        form = self._form_class( profile = profile, plans = plans, handle = handle )
        return antinode.response(
            main_content = self._form( request, handle, form, profile ),
            replace_map  = { 'vehicle-plan-list':
                             self._list( request, profile, plans, current_card_key( handle ) ) } )

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        form = self._form_class( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'vehicle-editor': self._form( request, handle, form, profile ) } )
        _profile, plans = form.apply( profile, plans )
        save_plans( current_plans_record( request ), plans )
        return antinode.response(
            replace_map = { 'vehicle-plan-list':
                            self._list( request, profile, plans, current_card_key( handle ) ) } )

    def _list( self, request, profile, plans, active = None ):
        return render_to_string(
            self._LIST_TEMPLATE,
            { 'cards': vehicle_plan_cards( profile, plans ), 'active': active },
            request = request )

    def _form( self, request, handle, form, profile ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { self._form_context_key: form, 'handle': handle,
              'heading': vehicle_heading( profile, handle ) },
            request = request )


class VehicleDispositionView( _VehicleDispositionView ):
    """`/inputs/interview/vehicle-expenses/current/<handle>/` -- the owned-vehicle disposition editor
    (Retain/Sell/Replace)."""

    _FORM_TEMPLATE    = 'inputs/interview/sections/vehicle_disposition_form.html'
    _form_class       = VehicleDispositionForm
    _form_context_key = 'disposition_form'


class LeasedVehicleDispositionView( _VehicleDispositionView ):
    """`/inputs/interview/vehicle-expenses/leased/<handle>/` -- the leased twin: the end-of-term editor
    (Return/Renew/Buy) plus its current lease terms, sharing the one list and form area."""

    _FORM_TEMPLATE    = 'inputs/interview/sections/leased_disposition_form.html'
    _form_class       = LeasedVehicleDispositionForm
    _form_context_key = 'leased_form'


class RecurringExpensesView( TotalsPaneMixin, SelfSavingPaneView ):
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


class PropertyExpensesView( TotalsPaneMixin, SelfSavingPaneView ):
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


class VehicleExpensesView( TotalsPaneMixin, SelfSavingPaneView ):
    """`/inputs/interview/vehicle-expenses/costs/edit/` -- the per-car running-costs table of the
    Vehicle plan step. Auto-saves each edit onto the vehicle plan's running costs; the row set is
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


def _mint_or_explain( request, mint, label ):
    """A freshly minted aggregate record for a writer. A read-only member cannot write, so minting one on
    read would be refused with a generic authorization error -- instead say plainly that the household has
    no such input yet. A near-edge case: reached only when an input was never created by a writer (so the
    empty initial record was never written)."""
    if not getattr( request, 'organization_can_write', True ):
        raise DataNotAvailableError( f'This household has no {label} data set up yet.' )
    return mint( request.organization )


def _mint_profile( request ):
    """The household's first profile, seeded from any facts the visitor carried in from the login-free
    tools (see `ucfp.session_facts`). Routed through `_mint_or_explain` so a read-only member gets the
    plain 'no profile yet' message rather than a generic authorization error. Reached only when the
    household has no profile at all, so the seed always fills a blank slate."""
    return _mint_or_explain(
        request,
        lambda organization: create_profile( organization, request.session_state.session_facts ),
        'Profile' )


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
    return latest_plans( organization ) or _mint_or_explain( request, create_plans, 'Plans' )


def current_assumptions_record( request ):
    """The Assumptions record the user is editing -- the session-selected one (scoped to the org),
    else the latest, minting one if the org has none."""
    organization = request.organization
    uuid = request.session_state.current_assumptions_uuid
    if uuid is not None:
        selected = assumptions_for( organization ).filter( uuid = uuid ).first()
        if selected is not None:
            return selected
    return latest_assumptions( organization ) or _mint_or_explain(
        request, create_assumptions, 'Assumptions' )


def _current_profile( request ):
    """The user's current Profile -- the latest month's, creating one if the org has none yet."""
    organization = request.organization
    record = latest_profile( organization ) or _mint_profile( request )
    return load_profile( record )


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


class NetWorthView( SelfSavingPaneView ):
    """`/inputs/interview/net-worth/edit/` -- the Net Worth pane of the Assumptions flow. It persists the
    latent-tax rates the Estimated Future Taxes overlay applies to pre-tax balances and unrealized gains."""

    template     = 'inputs/interview/sections/net_worth_pane.html'
    target       = 'net-worth'
    context_name = 'net_worth_form'

    def build_form( self, request, data = None ):
        return NetWorthForm( data, assumptions = _current_assumptions( request ) )

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
    single edit in the background: it persists the household (and the derived filing status), prunes the
    departed partner's own profile facts (their accounts, income, and entitlements), and refreshes the
    read-only filing-status readout beside the form, re-rendering the pane itself only on a genuine field
    error (a half-entered partner).
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
        # Dropping a partner prunes their own profile facts (accounts, income, entitlements); the plans
        # that still reference them are left as drift, reconciled on demand, not here. Both are saved
        # together through the paired-save seam.
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


@method_decorator( ensure_organization, name = 'dispatch' )
class _CurrentVehicleListView( View ):
    """Shared, org-scoped base for the Vehicles (Profile) section's one list -- the household's current
    vehicles, owned and leased together. The per-vehicle add/edit/delete swaps refresh this list."""

    _LIST_TEMPLATE = 'inputs/interview/sections/current_vehicle_list.html'

    def _list( self, request, profile, active = None ):
        # `active` is the handle whose editor is open, so the list can mark that row (the form detaches
        # from its row, so the highlight ties them back together).
        return render_to_string(
            self._LIST_TEMPLATE, { 'vehicles': current_vehicles_context( profile ), 'active': active },
            request = request )


class CurrentVehicleFormView( _CurrentVehicleListView ):
    """`/inputs/interview/vehicles/add/` and `.../<handle>/` -- the add/edit form for one current vehicle
    (owned or leased), opened as a card headed by the vehicle's name. Add and edit converge on a minted
    handle. Opening or saving marks the edited row in the list; POST background-saves (non-blocking)."""

    _FORM_TEMPLATE = 'inputs/interview/sections/current_vehicle_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):                  # close: empty the editor, clear the row mark
            return antinode.response(
                main_content = self._form( request, None, None, profile ),
                replace_map  = { 'current-vehicles-list': self._list( request, profile ) } )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_current_vehicle_handle( profile )
        form = CurrentVehicleForm( profile = profile, plans = plans, handle = handle )
        return antinode.response(
            main_content = self._form( request, handle, form, profile ),
            replace_map  = { 'current-vehicles-list': self._list( request, profile, active = handle ) },
            scroll_to    = 'current-vehicle-editor' )   # bring the editor into view on the stacked layout

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = CurrentVehicleForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'current-vehicle-editor': self._form( request, handle, form, profile ) } )
        # A vehicle write is a paired edit: it may reap a stale disposition when ownership flips, so
        # profile and plans commit together (the paired-save seam).
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response(
            replace_map = { 'current-vehicles-list': self._list( request, profile, active = handle ) } )

    def _form( self, request, handle, form, profile ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'vehicle_form': form, 'handle': handle,
              'heading': vehicle_heading( profile, handle ) if handle else None },
            request = request )


class CurrentVehicleDeleteView( _CurrentVehicleListView ):
    """`/inputs/interview/vehicles/<handle>/delete/` -- remove a current vehicle (its holding and secured
    loan, or its lease fact) and its vehicle-plan disposition, then refresh the list."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = delete_current_vehicle( profile, plans, handle )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response( replace_map = { 'current-vehicles-list': self._list( request, profile ) } )


@method_decorator( ensure_organization, name = 'dispatch' )
class _DebtListView( View ):
    """Shared, org-scoped base for the Debts section's one list -- the household's debts, editable loans
    and read-only mortgages/autos together. The per-debt add/edit/delete swaps refresh this list."""

    _LIST_TEMPLATE = 'inputs/interview/sections/debts_list.html'

    def _list( self, request, profile, active = None ):
        # `active` is the handle whose editor is open, so the list can mark that row (the form detaches
        # from its row, so the highlight ties them back together).
        return render_to_string(
            self._LIST_TEMPLATE, { 'debts': debts_context( profile ), 'active': active },
            request = request )


class DebtFormView( _DebtListView ):
    """`/inputs/interview/debt/add/` and `.../<handle>/` -- the add/edit form for one debt, opened as a card
    headed by the debt's name. Add and edit converge on a minted handle. Opening or saving marks the edited
    row in the list; POST background-saves (non-blocking)."""

    _FORM_TEMPLATE = 'inputs/interview/sections/debt_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):                  # close: empty the editor, clear the row mark
            return antinode.response(
                main_content = self._form( request, None, None, profile ),
                replace_map  = { 'debts-list': self._list( request, profile ) } )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_debt_handle( profile )
        form = DebtForm( profile = profile, plans = plans, handle = handle )
        return antinode.response(
            main_content = self._form( request, handle, form, profile ),
            replace_map  = { 'debts-list': self._list( request, profile, active = handle ) },
            scroll_to    = 'debt-editor' )             # bring the editor into view on the stacked layout

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = DebtForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'debt-editor': self._form( request, handle, form, profile ) } )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response(
            replace_map = { 'debts-list': self._list( request, profile, active = handle ) } )

    def _form( self, request, handle, form, profile ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'debt_form': form, 'handle': handle,
              'heading': debt_heading( profile, handle ) if handle else None },
            request = request )


class DebtDeleteView( _DebtListView ):
    """`/inputs/interview/debt/<handle>/delete/` -- remove a debt, then refresh the list. Plans are left as
    drift (reconciled on demand), not eagerly reaped."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = delete_debt( profile, plans, handle )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response( replace_map = { 'debts-list': self._list( request, profile ) } )


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
        """The general income lines (the only rows whose count changes); the rental rows are fixed by the
        properties."""
        return sum( 1 for flow in profile.income_flows if flow.property_handle is None )


class RetirementBenefitsView( SelfSavingPaneView ):
    """`/inputs/interview/retirement-benefits/edit/` -- the per-person Social Security and pension amounts.
    Its row set is fixed by the household (one pair per subject), so every valid edit saves silently; it
    writes only the entitlement facts, leaving the income flows to `IncomeTableView`."""

    template     = 'inputs/interview/sections/retirement_benefits_table.html'
    target       = 'retirement-benefits-table'
    context_name = 'benefits_form'

    def build_form( self, request, data = None ):
        profile, _plans = _current_profile_and_plans( request )
        return RetirementBenefitsForm( data, profile = profile )

    def persist( self, request, form ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return False                                            # fixed row set -- never re-renders


_SS_ESTIMATOR_TEMPLATE     = 'inputs/modals/social_security_estimator.html'
_SS_ESTIMATOR_FRA_TEMPLATE = 'inputs/modals/social_security_estimator_fra.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class SocialSecurityEstimatorModalView( ModalView ):
    """`/inputs/interview/retirement-benefits/estimate/<handle>/` -- the FRA-benefit calculator the
    Retirement benefits table opens beside a subject's Social Security cell. It seeds the average income
    from the subject's summed wages and shows the estimated monthly benefit at full retirement age (GET),
    recomputing that estimate as the user adjusts the income while the modal stays open (POST). Available
    only where the jurisdiction has an estimator -- the same gate the table's opener applies."""

    def get_template_name( self ):
        return _SS_ESTIMATOR_TEMPLATE

    def get( self, request, handle ):
        subject, pension, income = self._resolve( request, handle )
        form = SocialSecurityEstimatorForm( initial = {
            'income' : income, 'fra_benefit' : pension.estimate_entitlement( income ) } )
        return self.modal_response( request, context = {
            'form' : form, 'subject_handle' : handle, 'subject_name' : subject.name,
            'table_target' : RetirementBenefitsView.target } )

    def post( self, request, handle ):
        _subject, pension, _income = self._resolve( request, handle )
        income  = self._submitted_income( request )
        rendered = SocialSecurityEstimatorForm( initial = {
            'fra_benefit' : pension.estimate_entitlement( income ) } )
        content = render_to_string( _SS_ESTIMATOR_FRA_TEMPLATE, { 'form' : rendered }, request = request )
        return antinode.response( replace_map = { 'ss-estimator-fra' : content } )

    def _resolve( self, request, handle ):
        """The subject, the jurisdiction pension facade, and the subject's summed wages -- 404 for an
        unknown subject, or for a jurisdiction with no estimator (so the endpoint mirrors the opener's
        gate rather than returning a bad estimate)."""
        profile, _plans = _current_profile_and_plans( request )
        subject = next( ( candidate for candidate in profile.subjects if candidate.handle == handle ), None )
        if subject is None:
            raise Http404( f'No subject {handle!r} in the current profile.' )
        pension = GovernmentPension( profile.jurisdiction_type )
        if not pension.has_benefit_estimator():
            raise Http404( 'The current jurisdiction has no Social Security benefit estimator.' )
        return subject, pension, subject_wage_total( profile, handle )

    @staticmethod
    def _submitted_income( request ) -> Decimal:
        """The posted income parsed through the form's money field -- a blank or unparseable value falls
        back to zero, so the recompute always yields an estimate rather than erroring mid-interaction."""
        submitted = SocialSecurityEstimatorForm( request.POST )
        income    = submitted.cleaned_data.get( 'income' ) if submitted.is_valid() else None
        return income if income is not None else Decimal( 0 )


@method_decorator( ensure_organization, name = 'dispatch' )
class SocialSecurityBenefitApplyView( View ):
    """`.../retirement-benefits/estimate/<handle>/apply/` -- the calculator's Confirm. Writes the chosen
    benefit as the subject's Social Security entitlement fact (a blank clears it), then re-renders the
    benefits table so the cell shows it; the modal closes on return (its Confirm form is not marked
    stay-in-modal). Only this one subject's entitlement is touched -- the calculator edits one person. An
    invalid benefit leaves the stored entitlement untouched -- a bad submission never destroys it."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        if not any( subject.handle == handle for subject in profile.subjects ):
            raise Http404( f'No subject {handle!r} in the current profile.' )
        submitted = SocialSecurityEstimatorForm( request.POST )
        # A blank benefit is valid (the field is optional) and clears the entitlement; a value sets it.
        # Only a valid form writes: an invalid benefit (e.g. a negative) must NOT fall through to a clear,
        # which would silently destroy a stored figure. On invalid we skip the write and re-render the
        # table unchanged.
        if submitted.is_valid():
            profile = applied_government_benefit(
                profile, handle, submitted.cleaned_data.get( 'fra_benefit' ) )
            _save_profile_and_plans( request, profile, plans )
        pane = render_to_string(
            RetirementBenefitsView.template,
            { RetirementBenefitsView.context_name: RetirementBenefitsForm( profile = profile ) },
            request = request )
        return antinode.response( replace_map = { RetirementBenefitsView.target: pane } )


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
class _PropertyListView( View ):
    """Shared, org-scoped base for the Other Property section's one list -- the household's rentals and
    second homes together. The per-property add/edit/delete swaps refresh this list."""

    _LIST_TEMPLATE = 'inputs/interview/sections/property_list.html'

    def _list( self, request, profile, active = None ):
        # `active` is the handle whose editor is open, so the list can mark that row (the form detaches
        # from its row, so the highlight ties them back together).
        return render_to_string(
            self._LIST_TEMPLATE, { 'properties': properties_context( profile ), 'active': active },
            request = request )


class PropertyFormView( _PropertyListView ):
    """`/inputs/interview/property/add/` and `.../<handle>/` -- the add/edit form for one other-property
    holding (rental or second home), opened as a card headed by the property's name. Add and edit converge
    on a minted handle. Opening or saving marks the edited row in the list; POST background-saves
    (non-blocking)."""

    _FORM_TEMPLATE = 'inputs/interview/sections/property_form.html'

    def get( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):                  # close: empty the editor, clear the row mark
            return antinode.response(
                main_content = self._form( request, None, None, profile ),
                replace_map  = { 'properties-list': self._list( request, profile ) } )
        if handle is None:                             # add: mint a fresh handle, open its editor
            handle = _minted_handle( profile, PropertyForm._PREFIX )
        form = PropertyForm( profile = profile, plans = plans, handle = handle )
        return antinode.response(
            main_content = self._form( request, handle, form, profile ),
            replace_map  = { 'properties-list': self._list( request, profile, active = handle ) },
            scroll_to    = 'property-editor' )             # bring the editor into view on the stacked layout

    def post( self, request, handle = None ):
        profile, plans = _current_profile_and_plans( request )
        form = PropertyForm( request.POST, profile = profile, plans = plans, handle = handle )
        if not form.is_valid():
            return antinode.response(                          # surface a genuine field error
                replace_map = { 'property-editor': self._form( request, handle, form, profile ) } )
        profile, plans = form.apply( profile, plans )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response(
            replace_map = { 'properties-list': self._list( request, profile, active = handle ) } )

    def _form( self, request, handle, form, profile ):
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'property_form': form, 'handle': handle,
              'heading': property_heading( profile, handle ) if handle else None },
            request = request )


class PropertyDeleteView( _PropertyListView ):
    """`/inputs/interview/property/<handle>/delete/` -- remove an other-property holding as a unit (its
    holding, gross income, and secured mortgage), then refresh the list. Plans are left as drift."""

    def post( self, request, handle ):
        profile, plans = _current_profile_and_plans( request )
        profile, plans = delete_property( profile, plans, handle )
        _save_profile_and_plans( request, profile, plans )
        return antinode.response( replace_map = { 'properties-list': self._list( request, profile ) } )


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
        add_url    = reverse( 'event_add', kwargs = { 'kind': kind } )
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'form': form, 'kind': kind, 'group': event_type.group, 'title': event_type.label,
              'description': event_type.description, 'submit_label': 'Add',
              'action_url': add_url, 'cancel_url': f'{add_url}?collapse=1' },
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


@method_decorator( ensure_organization, name = 'dispatch' )
class EventEditView( View ):
    """`/inputs/interview/events/edit/<index>/` -- edit the event at `index` in place. GET opens its
    kind's form pre-filled from the event (or, with `collapse`, restores the add menu); POST validates it
    and replaces the event at `index`, keeping its kind, then refreshes the list and resets the add area.

    Editing is a straight replace: no editable kind provisions an entity or cascades on add, so unlike
    delete there is nothing to unwind (the `cascade_on_remove`/`cascade_on_add` pair is run for
    forward-safety, but is a no-op for every editable kind today). A non-editable or drifted event never
    reaches here from the UI (its row shows no Edit), and is treated as a no-op if its URL is hit directly.
    """

    _MENU_TEMPLATE = 'inputs/interview/sections/events_menu.html'
    _FORM_TEMPLATE = 'inputs/interview/sections/event_form.html'
    _LIST_TEMPLATE = 'inputs/interview/sections/events_list.html'

    def get( self, request, index ):
        profile, plans = _current_profile_and_plans( request )
        if request.GET.get( 'collapse' ):
            return antinode.response( main_content = self._menu( request, profile ) )
        event = self._editable_event( profile, plans, index )
        if event is None:                       # gone, out of range, non-editable, or drifted -- no form
            return antinode.response( main_content = self._menu( request, profile ) )
        handler = handler_for( event.kind )
        form    = EventForm( event_type = handler, profile = profile, event = event )
        return antinode.response( main_content = self._form( request, index, handler, form ) )

    def post( self, request, index ):
        organization   = request.organization
        profile, plans = _current_profile_and_plans( request )
        event = self._editable_event( profile, plans, index )
        if event is None:
            return antinode.response(
                main_content = self._menu( request, profile ),
                replace_map  = { 'events-list': self._list( request, profile, plans ) } )
        handler = handler_for( event.kind )
        form    = EventForm( request.POST, event_type = handler, profile = profile, event = event )
        if not form.is_valid():
            return antinode.response( main_content = self._form( request, index, handler, form ) )
        original = profile
        updated  = form.build_event()
        events   = list( plans.events )
        profile, plans = handler.cascade_on_remove( event, profile, plans )
        profile, plans = handler.cascade_on_add( updated, profile, plans )
        # Replace at `index`. This holds because no editable kind's cascade touches the events list (only
        # the non-editable card payoff cascades, on removal) -- so the list is the one captured above. The
        # assertion makes that invariant fail loudly rather than silently overwriting the wrong event if a
        # future editable kind ever cascades on it.
        assert list( plans.events ) == events, 'an editable kind cascaded on the events list'
        events[ index ] = updated
        plans = replace( plans, events = events )
        with transaction.atomic():
            if profile is not original:   # a cascade adjusted facts (no editable kind does today)
                save_profile( organization, profile )
            save_plans( current_plans_record( request ), plans )
        return antinode.response(
            main_content = self._menu( request, profile ),
            replace_map  = { 'events-list': self._list( request, profile, plans ) } )

    @staticmethod
    def _editable_event( profile, plans, index ):
        """The event at `index` when it exists and may be edited (an editable kind, references intact),
        else None -- the guard the GET/POST share so a stale or hand-typed URL degrades to a no-op."""
        events = list( plans.events )
        if not ( 0 <= index < len( events ) ):
            return None
        event = events[ index ]
        if not handler_for( event.kind ).is_editable( event, profile ):
            return None
        return event

    def _menu( self, request, profile ):
        return render_to_string(
            self._MENU_TEMPLATE, { 'menu': menu_context( profile ) }, request = request )

    def _form( self, request, index, event_type, form ):
        edit_url = reverse( 'event_edit', kwargs = { 'index': index } )
        return render_to_string(
            self._FORM_TEMPLATE,
            { 'form': form, 'kind': event_type.kind.name.lower(), 'group': event_type.group,
              'title': event_type.label, 'description': event_type.description, 'submit_label': 'Save',
              'action_url': edit_url, 'cancel_url': f'{edit_url}?collapse=1' },
            request = request )

    def _list( self, request, profile, plans ):
        return render_to_string(
            self._LIST_TEMPLATE, { 'events': events_context( profile, plans ) }, request = request )
