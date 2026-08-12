"""The Explore workspace's orchestration: run the working scenario and list its transient runs.

Explore forks a saved scenario into the organization's single WORKING scenario (see
`inputs.scenarios.repository`), then re-runs it as the user tweaks. Each run is captured as a WORKING
`PlanningResultRecord` -- the transient exploration history, distinct from the SAVED runs the user keeps.
"""
from typing import Optional

from common.dataclass_json import from_json_data

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import ScenarioRecord
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.scenarios.exploration import (
    enter_exploration, scenario_exploration, working_scenario )
from ucfp.inputs.scenarios.repository import load_scenario
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


def start_fresh_exploration( organization: Organization, source: ScenarioRecord ) -> None:
    """Start a fresh exploration of `source`: seed the working copy from it, anchor the exploration to it,
    and clear the prior session's transient runs, so the workspace re-projects the entered scenario's
    *current* state rather than showing a stale run from an earlier session. The initial run is produced
    lazily by the workspace view once no transient runs remain. The planning-side wrapper over the inputs
    seam `enter_exploration`: it adds the transient-run clear that makes the session *fresh* (re-entering
    the same anchor without this -- a plain resume -- deliberately keeps the runs)."""
    enter_exploration( organization, source )
    clear_transient_runs( organization )


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
    # A transient run is labelled by what it changed; its provenance is the anchor scenario it varies.
    exploration  = scenario_exploration( organization )
    source_label = exploration.source.label if exploration is not None else None
    run = run_and_capture(
        organization = organization, profile = load_profile( profile_record ),
        plans = scenario.plans, assumptions = scenario.assumptions, frame = frame, label = label,
        source_label = source_label )
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


def delete_runs( results ) -> None:
    """Delete the given captured runs by dropping each one's books; the `ProjectionRunRecord`
    and `PlanningResultRecord` cascade away, so no orphans remain. One bulk delete over the books (each
    run's `books_id` read straight off the joined-in run, never traversing a possibly-gone books row), so
    it stays correct even when another teardown -- an organization cascade -- is removing the same rows
    concurrently. The single home for the how; callers choose which runs (a recency-pruned transient set,
    a whole exploration's runs, or one saved run the user deleted)."""
    book_ids = [ result.run.books_id for result in results ]
    BooksOfAccountRecord.objects.filter( pk__in = book_ids ).delete()
    return


def _prune_transient_runs( organization: Organization ) -> None:
    """Drop the oldest transient runs beyond the retention cap -- the recency-bounded recovery buffer."""
    delete_runs( transient_runs( organization )[ _TRANSIENT_KEEP: ] )
    return


def clear_transient_runs( organization: Organization ) -> None:
    """Drop every transient run -- the fresh-session reset when *starting* (or Resetting) an exploration,
    and the teardown when an exploration is deleted (its anchor removed). Kept SAVED runs are untouched, as
    they are not transient."""
    delete_runs( transient_runs( organization ) )
    return
