"""The organization's single scenario exploration -- the WORKING sandbox and the SAVED anchor it is
measured against.

A `ScenarioExploration` *owns* a WORKING `ScenarioRecord` (a scenario referencing WORKING copies of a
Plans and an Assumptions the user tweaks freely) and names the SAVED `source` it was seeded from. This is
the lifecycle seam for the sandbox: enter/re-seed it from a chosen scenario, overwrite its values as the
user tweaks, and save it -- `save_working` writes each component either into the source's existing (shared)
set or into a new independent one, per an explicit per-component choice. The SAVED-scenario CRUD and
reference resolution live next door in `repository.py`.
"""
from typing import Optional

from django.db import transaction

from organization.models import Organization

from ..assumptions.repository import (
    assumptions_labels, clone_assumptions, rename_assumptions, save_assumptions )
from ..enums import UsageRole
from ..models import AssumptionsRecord, PlansRecord, ScenarioExploration, ScenarioRecord
from ..naming import unique_label
from ..plans.repository import clone_plans, plans_labels, rename_plans, save_plans
from .repository import create_scenario, load_scenario, scenario_labels
from .schemas import Scenario

# A component's save destination: OVERWRITE the source's existing (shared) set in place, or COPY the
# working values into a new independent set. The view posts these as the `dest_<component>` field values.
OVERWRITE = 'overwrite'
COPY      = 'copy'


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
        organization: Organization, source: ScenarioRecord, destinations: dict[ str, str ],
        name: str = '' ) -> ScenarioRecord:
    """Persist the sandbox against `source`, per component. `destinations` maps 'plans' and 'assumptions' to
    `OVERWRITE` (write the working values into `source`'s existing set, in place -- propagating to every
    scenario that shares it) or `COPY` (a new independent set holding the working values); a missing or
    unrecognised value defaults to `OVERWRITE`.

    If every component is `OVERWRITE`, `source` itself is updated in place and returned -- no new scenario.
    If any is `COPY`, a new scenario named `name` (a distinct "<source> copy" when `name` is blank) is
    created: its `COPY` components are new independent sets,
    its `OVERWRITE` components are `source`'s existing sets (shared, and written in place). Either way the
    exploration re-anchors to the result. Raises if there is no working scenario.

    This is the one save primitive: an all-`OVERWRITE` call is "update this scenario", an all-`COPY` call is
    "save as a new independent scenario", and a mix branches while sharing the overwritten sets -- each an
    explicit choice of what propagates."""
    exploration = scenario_exploration( organization )
    if exploration is None:
        raise ValueError( 'No working scenario to save.' )
    destinations = { component: ( COPY if destinations.get( component ) == COPY else OVERWRITE )
                     for component in ( 'plans', 'assumptions' ) }   # normalise: fill/repair to a clean pair
    sandbox = load_scenario( exploration.working )
    # The name for a copied set / new scenario; an unnamed save defaults to a distinct "<source> copy".
    label   = name.strip() or unique_label( f'{source.label} copy', scenario_labels( organization ) )
    with transaction.atomic():                             # writes, new scenario, and re-anchor together
        if destinations[ 'plans' ] == OVERWRITE:
            plans = save_plans( source.plans, sandbox.plans )   # in place; propagates to any sharer
        else:
            plans = rename_plans(
                save_plans( clone_plans( source.plans ), sandbox.plans ),
                unique_label( f'{label} Plans', plans_labels( organization ) ) )
        if destinations[ 'assumptions' ] == OVERWRITE:
            assumptions = save_assumptions( source.assumptions, sandbox.assumptions )
        else:
            assumptions = rename_assumptions(
                save_assumptions( clone_assumptions( source.assumptions ), sandbox.assumptions ),
                unique_label( f'{label} Assumptions', assumptions_labels( organization ) ) )
        # A copy needs a home scenario; when nothing is copied, the source's identity is unchanged. The
        # copied component sets are deduped above, but the user-typed scenario name is left to collide if
        # they reuse it -- as the New Scenario flow also allows.
        record = ( create_scenario( organization, plans, assumptions, label )
                   if COPY in destinations.values() else source )
        exploration.source = record
        exploration.save()
        return record


def component_usage( source: ScenarioRecord ) -> dict[ str, int ]:
    """How many *other* scenarios reference each of `source`'s components -- the sharing scope, for showing
    it and for defaulting a component's save to an in-place overwrite (private: no others) or a protective
    copy (shared: some). SAVED scenarios only, since the working sandbox references its own copies."""
    return {
        'plans'       : source.plans.scenarios.exclude( pk = source.pk ).count(),
        'assumptions' : source.assumptions.scenarios.exclude( pk = source.pk ).count() }


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
