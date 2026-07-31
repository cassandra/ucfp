"""The organization's single scenario exploration -- the WORKING sandbox and the SAVED anchor it is
measured against.

A `ScenarioExploration` *owns* a WORKING `ScenarioRecord` (a scenario referencing WORKING copies of a
Plans and an Assumptions the user tweaks freely) and names the SAVED `source` it was seeded from. This is
the lifecycle seam for the sandbox: enter/re-seed it from a chosen scenario, overwrite its values as the
user tweaks, and write it back -- Update over the source's shared components (propagation intended), or
Save-as-new forking the changed component(s) into new SAVED components and re-anchoring the exploration to
the result. The SAVED-scenario CRUD and reference resolution live next door in `repository.py`.
"""
from typing import Optional

from django.db import transaction

from organization.models import Organization

from ..assumptions.repository import (
    assumptions_for, clone_assumptions, rename_assumptions, save_assumptions )
from ..enums import UsageRole
from ..models import AssumptionsRecord, PlansRecord, ScenarioExploration, ScenarioRecord
from ..naming import unique_label
from ..plans.repository import clone_plans, plans_for, rename_plans, save_plans
from .repository import create_scenario, load_scenario
from .schemas import Scenario


def scenario_exploration( organization: Organization ) -> Optional[ ScenarioExploration ]:
    """The organization's single in-progress exploration, or None before one is entered."""
    return ScenarioExploration.objects.filter( organization = organization ).first()


def working_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The WORKING scenario the current exploration owns (the sandbox), or None when none is in progress."""
    exploration = scenario_exploration( organization )
    return exploration.working if exploration is not None else None


def enter_exploration( organization: Organization, source: ScenarioRecord ) -> ScenarioExploration:
    """Seed the sandbox from `source` and anchor the exploration to it: overwrite the WORKING component
    copies in place when an exploration already exists, or mint the exploration (its WORKING scenario
    referencing fresh WORKING Plans + Assumptions) on first use. The explore-entry step that forks a chosen
    scenario's current inputs into the loop; `source` is the baseline drift is later measured against."""
    scenario = load_scenario( source )
    with transaction.atomic():                             # exploration and sandbox trio move as a unit
        exploration = scenario_exploration( organization )
        if exploration is not None:
            save_plans( exploration.working.plans, scenario.plans )
            save_assumptions( exploration.working.assumptions, scenario.assumptions )
            exploration.source = source
            exploration.save()
            return exploration
        working = _mint_working( organization, scenario )
        return ScenarioExploration.objects.create(
            organization = organization, working = working, source = source )


def overwrite_working( organization: Organization, scenario: Scenario ) -> Optional[ ScenarioRecord ]:
    """Overwrite the sandbox's values in place with `scenario`, leaving the anchor untouched -- how a tweak
    autosaves as the user edits. None when no exploration is in progress."""
    working = working_scenario( organization )
    if working is None:
        return None
    with transaction.atomic():                             # both component copies update together, or neither
        save_plans( working.plans, scenario.plans )
        save_assumptions( working.assumptions, scenario.assumptions )
    return working


def save_working(
        organization: Organization, source: ScenarioRecord, destinations: dict,
        name: str = '' ) -> ScenarioRecord:
    """Persist the sandbox against `source`, per component. `destinations` maps 'plans' and 'assumptions' to
    'overwrite' (write the working values into `source`'s existing set, in place -- propagating to every
    scenario that shares it) or 'copy' (a new independent set holding the working values).

    If every component is 'overwrite', `source` itself is updated in place and returned -- no new scenario.
    If any is 'copy', a new scenario named `name` is created: its 'copy' components are new independent sets,
    its 'overwrite' components are `source`'s existing sets (shared, and written in place). Either way the
    exploration re-anchors to the result. Raises if there is no working scenario.

    This is the one save primitive: an all-'overwrite' call is "update this scenario", an all-'copy' call is
    "save as a new independent scenario", and a mix branches while sharing the overwritten sets -- each an
    explicit choice of what propagates."""
    exploration = scenario_exploration( organization )
    if exploration is None:
        raise ValueError( 'No working scenario to save.' )
    sandbox = load_scenario( exploration.working )
    label   = name.strip() or 'Saved scenario'             # only when a component is copied into a new set
    with transaction.atomic():                             # writes, new scenario, and re-anchor together
        if destinations[ 'plans' ] == 'overwrite':
            plans = save_plans( source.plans, sandbox.plans )   # in place; propagates to any sharer
        else:
            plans = rename_plans(
                save_plans( clone_plans( source.plans ), sandbox.plans ),
                unique_label( f'{label} Plans', _plans_labels( organization ) ) )
        if destinations[ 'assumptions' ] == 'overwrite':
            assumptions = save_assumptions( source.assumptions, sandbox.assumptions )
        else:
            assumptions = rename_assumptions(
                save_assumptions( clone_assumptions( source.assumptions ), sandbox.assumptions ),
                unique_label( f'{label} Assumptions', _assumptions_labels( organization ) ) )
        # A copy needs a home scenario; when nothing is copied, the source's identity is unchanged.
        record = ( create_scenario( organization, plans, assumptions, label )
                   if 'copy' in destinations.values() else source )
        exploration.source = record
        exploration.save()
        return record


def component_usage( source: ScenarioRecord ) -> dict:
    """How many *other* scenarios reference each of `source`'s components -- the sharing scope, for showing
    it and for defaulting a component's save to an in-place overwrite (private: no others) or a protective
    copy (shared: some). SAVED scenarios only, since the working sandbox references its own copies."""
    return {
        'plans'       : source.plans.scenarios.exclude( pk = source.pk ).count(),
        'assumptions' : source.assumptions.scenarios.exclude( pk = source.pk ).count() }


def save_working_over_scenario( organization: Organization, record: ScenarioRecord ) -> ScenarioRecord:
    """Write the sandbox's values into `record`'s Plans and Assumptions in place -- the 'update this
    scenario' action, an all-'overwrite' `save_working`. Propagates to every scenario sharing those sets,
    which is the intent. Raises if there is no working scenario."""
    return save_working( organization, record, { 'plans': 'overwrite', 'assumptions': 'overwrite' } )


def save_working_as_scenario(
        organization: Organization, label: str, source: ScenarioRecord,
        share: frozenset = frozenset() ) -> ScenarioRecord:
    """Fork the sandbox into a new saved scenario named `label`. Each component becomes a **new independent
    set** -- `source`'s set cloned and stamped with the sandbox's values (a plain copy where the user left it
    untouched, the tweak-fork where they changed it) -- unless the user explicitly asked to **share** an
    unchanged component with `source` (its key in `share`), in which case the new scenario references it so a
    later edit still propagates to both, by the user's choice. A *changed* component can never be shared (it
    diverged), so `share` is honoured only for components equal to the source's. Raises if there is no
    working scenario.

    A forked set is cloned from `source` (which carries its completeness) rather than from the sandbox copies
    (which hold only data), so it is runnable at once. Finally the exploration re-anchors to the new scenario,
    so the sandbox now represents it and a later Update targets it rather than the one it was forked from."""
    exploration = scenario_exploration( organization )
    if exploration is None:
        raise ValueError( 'No working scenario to save.' )
    sandbox = load_scenario( exploration.working )
    origin  = load_scenario( source )
    with transaction.atomic():                             # forks, new scenario, and re-anchor land together
        if 'plans' in share and sandbox.plans == origin.plans:
            plans = source.plans                           # shared by explicit choice: edits still propagate
        else:
            copy  = save_plans( clone_plans( source.plans ), sandbox.plans )
            plans = rename_plans( copy, unique_label( f'{label} Plans', _plans_labels( organization ) ) )
        if 'assumptions' in share and sandbox.assumptions == origin.assumptions:
            assumptions = source.assumptions
        else:
            copy        = save_assumptions( clone_assumptions( source.assumptions ), sandbox.assumptions )
            assumptions = rename_assumptions(
                copy, unique_label( f'{label} Assumptions', _assumptions_labels( organization ) ) )
        record = create_scenario( organization, plans, assumptions, label )
        exploration.source = record                        # the sandbox now represents the saved variation
        exploration.save()
        return record


def _plans_labels( organization: Organization ) -> list:
    return [ record.label for record in plans_for( organization ) ]


def _assumptions_labels( organization: Organization ) -> list:
    return [ record.label for record in assumptions_for( organization ) ]


def _mint_working( organization: Organization, scenario: Scenario ) -> ScenarioRecord:
    """Mint the WORKING sandbox trio -- a WORKING Plans and Assumptions seeded from `scenario`, and the
    WORKING scenario referencing them -- for a first-time exploration."""
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
