"""The seam between a `ScenarioRecord` and its typed `Scenario`, plus minting, listing, and the single
working copy.

A scenario is the durable, mutable unit the user keeps and re-runs over time; it fully owns a copy of
its inputs, embedded in the record's `data`, independent of any run. All reads and writes go through
here, so no caller handles the raw JSON. Records are partitioned by `usage_role`: the `SAVED` scenarios
are the user's kept set; one `WORKING` scenario per organization is the exploration tweak target,
overwritten wholesale on each fresh entry into the explore loop.
"""
from typing import Optional

from django.db.models import QuerySet

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from ..enums import UsageRole
from ..models import ScenarioRecord
from .schemas import Scenario


def load_scenario( record: ScenarioRecord ) -> Scenario:
    return from_json_data( Scenario, record.data )


def store_scenario( record: ScenarioRecord, scenario: Scenario ) -> None:
    record.data = to_json_data( scenario )


def save_scenario( record: ScenarioRecord, scenario: Scenario ) -> ScenarioRecord:
    """Persist `scenario` into `record` -- a specific scenario, overwriting its prior contents."""
    store_scenario( record, scenario )
    record.save()
    return record


def scenarios_for( organization: Organization ) -> QuerySet:
    """The organization's saved scenarios, most recent first. The working copy is excluded -- it is not
    a user-facing scenario."""
    return ScenarioRecord.objects.filter(
        organization = organization, usage_role = UsageRole.SAVED ).order_by( '-updated_datetime' )


def latest_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's most recent saved scenario, or None."""
    return scenarios_for( organization ).first()


def create_scenario( organization: Organization, scenario: Optional[ Scenario ] = None,
                     label: Optional[ str ] = None ) -> ScenarioRecord:
    """Mint a new saved scenario for `organization` -- empty inputs and a distinguishable label by
    default. The single place that decides a new scenario's initial content and name."""
    record = ScenarioRecord(
        organization = organization, usage_role = UsageRole.SAVED,
        label = label or _default_label( organization ) )
    return save_scenario( record, scenario or Scenario() )


def rename_scenario( record: ScenarioRecord, label: str ) -> ScenarioRecord:
    """Rename a scenario, leaving its inputs untouched."""
    record.label = label
    record.save()
    return record


def delete_scenario( record: ScenarioRecord ) -> None:
    """Delete a scenario. Runs snapshot their inputs, so nothing downstream depends on it."""
    record.delete()


def working_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's single working scenario (the exploration tweak target), or None if none yet."""
    return ScenarioRecord.objects.filter(
        organization = organization, usage_role = UsageRole.WORKING ).order_by( '-updated_datetime' ).first()


def set_working_scenario( organization: Organization, scenario: Scenario ) -> ScenarioRecord:
    """Seed the single working scenario with `scenario`, creating it on first use or overwriting it
    wholesale -- the explore-entry step that forks a chosen scenario (or fresh inputs) into the loop."""
    record = working_scenario( organization ) or ScenarioRecord(
        organization = organization, usage_role = UsageRole.WORKING, label = 'Working scenario' )
    return save_scenario( record, scenario )


def save_working_as_scenario( organization: Organization, label: str ) -> ScenarioRecord:
    """Promote the current working scenario's inputs into a new, independent saved scenario named
    `label` (a copy -- the working copy keeps churning). Raises if there is no working scenario."""
    working = working_scenario( organization )
    if working is None:
        raise ValueError( 'No working scenario to save.' )
    return create_scenario( organization, load_scenario( working ), label )


def save_working_over_scenario( organization: Organization, record: ScenarioRecord ) -> ScenarioRecord:
    """Overwrite an existing saved scenario `record` with the current working scenario's inputs (its name
    is left untouched) -- the 'update this scenario' action, versus `save_working_as_scenario`'s 'save a
    new one'. Raises if there is no working scenario."""
    working = working_scenario( organization )
    if working is None:
        raise ValueError( 'No working scenario to save.' )
    return save_scenario( record, load_scenario( working ) )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new scenario, since many coexist per organization."""
    return f'Scenario {scenarios_for( organization ).count() + 1}'
