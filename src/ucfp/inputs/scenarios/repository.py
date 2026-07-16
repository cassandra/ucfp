"""The seam between a `ScenarioRecord` (a reference to a Plans + an Assumptions) and its resolved typed
`Scenario`, plus minting, listing, and the single working sandbox.

A scenario is the durable unit the user keeps and re-runs over time. It does not copy its inputs: it
*references* a `PlansRecord` and an `AssumptionsRecord`, so refining a shared component is reflected in
every scenario that uses it. Records are partitioned by `usage_role`: SAVED scenarios are the user's kept
set; the single WORKING scenario per organization is the exploration sandbox, referencing WORKING copies
of a Plans and an Assumptions that the user tweaks freely -- Save writes those copies back into the
referenced SAVED components (propagation is intended), Save-as-new forks them into new SAVED components.
"""
from typing import Optional

from django.db.models import QuerySet

from organization.models import Organization

from ..assumptions.repository import clone_assumptions, load_assumptions, rename_assumptions, save_assumptions
from ..enums import UsageRole
from ..models import AssumptionsRecord, PlansRecord, ScenarioRecord
from ..plans.repository import clone_plans, load_plans, rename_plans, save_plans
from .schemas import Scenario


def load_scenario( record: ScenarioRecord ) -> Scenario:
    """The scenario's inputs, resolved from its referenced components -- the current values, so an edit to
    a shared Plans or Assumptions is visible through every scenario that references it."""
    return Scenario( plans = load_plans( record.plans ), assumptions = load_assumptions( record.assumptions ) )


def scenarios_for( organization: Organization ) -> QuerySet:
    """The organization's saved scenarios, most recent first. The working sandbox is excluded -- it is not
    a user-facing scenario."""
    return ScenarioRecord.objects.filter(
        organization = organization, usage_role = UsageRole.SAVED ).order_by( '-updated_datetime' )


def latest_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's most recent saved scenario, or None."""
    return scenarios_for( organization ).first()


def create_scenario( organization: Organization, plans: PlansRecord, assumptions: AssumptionsRecord,
                     label: Optional[ str ] = None ) -> ScenarioRecord:
    """Mint a saved scenario referencing the given Plans and Assumptions records -- the single place that
    decides a new scenario's default name."""
    return ScenarioRecord.objects.create(
        organization = organization, label = label or _default_label( organization ),
        plans = plans, assumptions = assumptions, usage_role = UsageRole.SAVED )


def rename_scenario( record: ScenarioRecord, label: str ) -> ScenarioRecord:
    """Rename a scenario, leaving its component references untouched."""
    record.label = label
    record.save()
    return record


def delete_scenario( record: ScenarioRecord ) -> None:
    """Delete a scenario -- only the pairing; its Plans and Assumptions live on for other scenarios."""
    record.delete()


def working_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's single working scenario (the exploration sandbox), or None if none yet."""
    return ScenarioRecord.objects.filter(
        organization = organization, usage_role = UsageRole.WORKING ).order_by( '-updated_datetime' ).first()


def set_working_scenario( organization: Organization, scenario: Scenario ) -> ScenarioRecord:
    """Seed the working sandbox with `scenario` -- overwriting the WORKING component copies in place, or
    minting the sandbox (a WORKING scenario referencing WORKING Plans + Assumptions) on first use. The
    explore-entry step that forks a chosen scenario's current inputs into the loop."""
    working = working_scenario( organization )
    if working is not None:
        save_plans( working.plans, scenario.plans )
        save_assumptions( working.assumptions, scenario.assumptions )
        return working
    working_plans = save_plans(
        PlansRecord( organization = organization, usage_role = UsageRole.WORKING, label = 'Working plans' ),
        scenario.plans )
    working_assumptions = save_assumptions(
        AssumptionsRecord(
            organization = organization, usage_role = UsageRole.WORKING, label = 'Working assumptions' ),
        scenario.assumptions )
    return ScenarioRecord.objects.create(
        organization = organization, label = 'Working scenario', usage_role = UsageRole.WORKING,
        plans = working_plans, assumptions = working_assumptions )


def save_working_over_scenario( organization: Organization, record: ScenarioRecord ) -> ScenarioRecord:
    """Write the sandbox's values into `record`'s referenced Plans and Assumptions -- the 'update this
    scenario' action. Because those components are shared, this propagates to every scenario referencing
    them, which is the intent. Raises if there is no working scenario."""
    working = working_scenario( organization )
    if working is None:
        raise ValueError( 'No working scenario to save.' )
    save_plans( record.plans, load_plans( working.plans ) )
    save_assumptions( record.assumptions, load_assumptions( working.assumptions ) )
    return record


def save_working_as_scenario(
        organization: Organization, label: str, source: ScenarioRecord ) -> ScenarioRecord:
    """Fork the sandbox into a new saved scenario named `label`, forking **only the component(s) the user
    changed** relative to `source`: a diverged component is copied into a new SAVED set (named after the
    scenario), an unchanged one is shared with `source` so edits to it still propagate to both. Raises if
    there is no working scenario."""
    working = working_scenario( organization )
    if working is None:
        raise ValueError( 'No working scenario to save.' )
    sandbox, origin = load_scenario( working ), load_scenario( source )
    plans = ( rename_plans( clone_plans( working.plans ), f'{label} Plans' )
              if sandbox.plans != origin.plans else source.plans )
    assumptions = ( rename_assumptions( clone_assumptions( working.assumptions ), f'{label} Assumptions' )
                    if sandbox.assumptions != origin.assumptions else source.assumptions )
    return create_scenario( organization, plans, assumptions, label )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new scenario, since many coexist per organization."""
    return f'Scenario {scenarios_for( organization ).count() + 1}'
