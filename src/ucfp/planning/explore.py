"""The Explore workspace's orchestration: run the working scenario and list its transient runs.

Explore forks a saved scenario into the organization's single WORKING scenario (see
`inputs.scenarios.repository`), then re-runs it as the user tweaks. Each run is captured as a WORKING
`PlanningResultRecord` -- the transient exploration history, distinct from the SAVED runs the user keeps.
"""
from typing import Optional

from common.dataclass_json import from_json_data

from organization.models import Organization

from ucfp.inputs.enums import UsageRole
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.scenarios.repository import load_scenario, set_working_scenario, working_scenario
from ucfp.inputs.scenarios.schemas import Scenario

from .enums import PlanningFeature
from .explore_diff import describe_changes, value_changes
from .materialization import ForecastFrame
from .models import PlanningResultRecord
from .orchestration import run_and_capture
from .schemas import ProjectionRun

# Transient (WORKING) runs retained per organization: a recovery buffer well beyond what the strip
# shows, so a good run tweaked past can still be recovered, without unbounded growth of run snapshots.
_TRANSIENT_KEEP = 25


def enter_explore( organization: Organization, scenario: Scenario ) -> None:
    """Fork `scenario` into the single working scenario -- the explore-entry seed, overwriting whatever
    working copy was there."""
    set_working_scenario( organization, scenario )


def run_working_scenario(
        organization: Organization, frame: ForecastFrame ) -> Optional[ PlanningResultRecord ]:
    """Run the organization's working scenario against its current profile over `frame`, capturing the
    result as a WORKING (transient) run labelled by what its inputs changed since the previous run. None
    when there is no working scenario or profile yet."""
    working        = working_scenario( organization )
    profile_record = latest_profile( organization )
    if working is None or profile_record is None:
        return None
    scenario = load_scenario( working )
    label    = _run_label( organization, scenario )
    run = run_and_capture(
        organization = organization, profile = load_profile( profile_record ),
        plans = scenario.plans, assumptions = scenario.assumptions, frame = frame, label = label )
    result = PlanningResultRecord.objects.create(
        organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
        run = run, label = label, usage_role = UsageRole.WORKING )
    _prune_transient_runs( organization )
    return result


def run_scenario( result: PlanningResultRecord ) -> Scenario:
    """The Scenario a captured run was produced from -- its embedded input snapshot (the provenance seam:
    a run is compared to a scenario by these inputs, never linked)."""
    run = from_json_data( ProjectionRun, result.run.data )
    return Scenario( plans = run.plans, assumptions = run.assumptions )


def _run_label( organization: Organization, scenario: Scenario ) -> str:
    """A transient run's label: what its inputs changed since the previous run (the first is the start)."""
    previous = transient_runs( organization ).first()
    if previous is None:
        return 'Starting point'
    return describe_changes( value_changes( run_scenario( previous ), scenario ) )


def transient_runs( organization: Organization ):
    """The organization's transient (WORKING) forecast runs, most recent first -- the exploration
    history strip."""
    return PlanningResultRecord.objects.filter(
        organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
        usage_role = UsageRole.WORKING ).select_related( 'run' ).order_by( '-updated_datetime' )


def _prune_transient_runs( organization: Organization ) -> None:
    """Drop the oldest transient runs beyond the retention cap. Deleting each captured run's books
    cascades to its `ProjectionRunRecord` and this `PlanningResultRecord`, so no orphans are left."""
    for result in list( transient_runs( organization )[ _TRANSIENT_KEEP: ] ):
        result.run.books.delete()
