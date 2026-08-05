"""The seam between a `ScenarioRecord` (a reference to a Plans + an Assumptions) and its resolved typed
`Scenario`, plus minting and listing the SAVED scenarios.

A scenario is the durable unit the user keeps and re-runs over time. It does not copy its inputs: it
*references* a `PlansRecord` and an `AssumptionsRecord`, so refining a shared component is reflected in
every scenario that uses it. Records are partitioned by `usage_role`: SAVED scenarios are the user's kept
set. The single WORKING sandbox and its save-back lifecycle (enter, tweak, Update, Save-as-new) live next
door in `exploration.py`.
"""
from typing import Optional

from django.core.exceptions import BadRequest
from django.db import transaction
from django.db.models import QuerySet

from organization.models import Organization

from ..assumptions.repository import create_assumptions, load_assumptions, rename_assumptions
from ..enums import UsageRole
from ..models import AssumptionsRecord, PlansRecord, ScenarioRecord
from ..naming import numbered_label
from ..plans.repository import create_plans, load_plans, rename_plans
from .schemas import Scenario


def load_scenario( record: ScenarioRecord ) -> Scenario:
    """The scenario's inputs, resolved from its referenced components -- the current values, so an edit to
    a shared Plans or Assumptions is visible through every scenario that references it."""
    plans       = load_plans( record.plans )
    assumptions = load_assumptions( record.assumptions )
    return Scenario( plans = plans, assumptions = assumptions )


def scenarios_for( organization: Organization ) -> QuerySet:
    """The organization's saved scenarios, most recent first. The working sandbox is excluded -- it is not
    a user-facing scenario."""
    return ScenarioRecord.objects.filter(
        organization = organization, usage_role = UsageRole.SAVED ).order_by( '-updated_datetime' )


def latest_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's most recent saved scenario, or None."""
    return scenarios_for( organization ).first()


def existing_pairings( organization: Organization ) -> set:
    """The (plans_uuid, assumptions_uuid) pairs the organization's scenarios already cover, as strings --
    so a new scenario can offer only combinations not yet defined (uuids to match the component choosers)."""
    return {
        ( str( plans_uuid ), str( assumptions_uuid ) )
        for plans_uuid, assumptions_uuid
        in scenarios_for( organization ).values_list( 'plans__uuid', 'assumptions__uuid' ) }


def create_scenario( organization: Organization, plans: PlansRecord, assumptions: AssumptionsRecord,
                     label: Optional[ str ] = None ) -> ScenarioRecord:
    """Mint a saved scenario referencing the given Plans and Assumptions records -- the single place that
    decides a new scenario's default name."""
    return ScenarioRecord.objects.create(
        organization = organization, label = label or _default_label( organization ),
        plans = plans, assumptions = assumptions, usage_role = UsageRole.SAVED )


def default_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's base scenario -- the oldest saved one, which the profile flow's shared data
    (the straddle sections' rental income) binds to. Oldest is a stable identity for the Default: there is
    no `is_default` marker, and by construction the first scenario an organization gets is the Default that
    profile setup creates. None before that first setup."""
    return scenarios_for( organization ).order_by( 'created_datetime' ).first()


def ensure_default_scenario( organization: Organization ) -> ScenarioRecord:
    """Guarantee the organization has a scenario for the Profile to bind to. On first profile setup it
    mints a `Default Plans` and `Default Assumptions` and combines them into a `Default Scenario` -- all
    incomplete until their flows are walked, so completeness detection still drives the setup. Idempotent:
    returns the existing base scenario when one is already present, so no duplicate Default is created."""
    with transaction.atomic():
        # Serialize per organization so a double-entry into profile setup can't mint two Defaults. The
        # SAVED partition has no uniqueness constraint and an empty scenario set can't be row-locked, so
        # the organization row is the lock (a no-op on SQLite, which serializes writes anyway).
        Organization.objects.select_for_update().filter( pk = organization.pk ).first()
        base = default_scenario( organization )
        if base is not None:
            return base
        plans       = rename_plans( create_plans( organization ), 'Default Plans' )
        assumptions = rename_assumptions( create_assumptions( organization ), 'Default Assumptions' )
        return create_scenario( organization, plans, assumptions, 'Default Scenario' )


def rename_scenario( record: ScenarioRecord, label: str ) -> ScenarioRecord:
    """Rename a scenario, leaving its component references untouched."""
    record.label = label
    record.save()
    return record


def delete_scenario( record: ScenarioRecord ) -> None:
    """Delete a scenario -- only the pairing; its Plans and Assumptions live on for other scenarios. If the
    scenario anchors an in-progress exploration, that exploration cascades away with it (see
    `ScenarioExploration`). Much of the app assumes a scenario exists, so the last one cannot be deleted:
    the UI hides the control, and a request that still arrives is malformed (BadRequest -> 400)."""
    if scenarios_for( record.organization ).count() <= 1:
        raise BadRequest( 'Cannot delete the last scenario.' )
    record.delete()


def would_orphan_all_scenarios( organization: Organization, *,
                                plans: Optional[ PlansRecord ] = None,
                                assumptions: Optional[ AssumptionsRecord ] = None ) -> bool:
    """Whether deleting the given component would cascade away every saved scenario -- because all of them
    pair it -- leaving the organization with none. The scenario delete guards deleting a scenario
    directly; this guards the indirect path, where deleting a Plans or Assumptions set cascades its
    scenarios away. Exactly one of `plans` / `assumptions` names the component being deleted."""
    scenarios = scenarios_for( organization )
    if not scenarios.exists():
        return False
    remaining = ( scenarios.exclude( plans = plans ) if plans is not None
                  else scenarios.exclude( assumptions = assumptions ) )
    return not remaining.exists()


def scenario_labels( organization: Organization ) -> list:
    """The labels of the organization's SAVED scenarios -- the taken names an auto-generated name avoids."""
    return [ record.label for record in scenarios_for( organization ) ]


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new scenario, since many coexist per organization."""
    return numbered_label( 'Scenario', scenario_labels( organization ) )
