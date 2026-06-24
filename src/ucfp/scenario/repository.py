"""The seam between a `ScenarioRecord` and its typed `Scenario` aggregate, plus minting and
listing.

All reads and writes of a scenario's data go through here, so no caller handles the raw JSON
dict -- the typed `Scenario` is the only form the rest of the app sees. Unlike a profile, a
scenario is not month-versioned: many labelled scenarios coexist per organization, and a save
overwrites the specific scenario being edited.
"""
from typing import Optional

from django.db.models import QuerySet

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from .models import ScenarioRecord
from .schemas import Scenario


def load_scenario( record: ScenarioRecord ) -> Scenario:
    return from_json_data( Scenario, record.data )


def store_scenario( record: ScenarioRecord, scenario: Scenario ) -> None:
    record.data = to_json_data( scenario )


def scenarios_for( organization: Organization ) -> QuerySet:
    """The organization's scenarios, most recent first."""
    return ScenarioRecord.objects.filter(
        organization = organization ).order_by( '-created_datetime' )


def latest_scenario( organization: Organization ) -> Optional[ ScenarioRecord ]:
    """The organization's most recent scenario, or None if it has none."""
    return scenarios_for( organization ).first()


def save_scenario( record: ScenarioRecord, scenario: Scenario ) -> ScenarioRecord:
    """Persist `scenario` into `record` -- a specific scenario, with no monthly versioning."""
    store_scenario( record, scenario )
    record.save()
    return record


def create_scenario( organization: Organization ) -> ScenarioRecord:
    """Mint a new scenario for `organization` and return its record -- the single, extensible
    place that decides a new scenario's initial content and label."""
    record = ScenarioRecord(
        organization = organization, label = _default_label( organization ) )
    return save_scenario( record, _initial_scenario() )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new scenario, since many coexist per organization."""
    return f'Scenario {scenarios_for( organization ).count() + 1}'


def _initial_scenario() -> Scenario:
    """The content a new scenario starts from -- the typed defaults (an Expected outlook, the
    general lifestyle scope); the extension point for richer seeding later."""
    return Scenario()
