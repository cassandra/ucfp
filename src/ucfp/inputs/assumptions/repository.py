"""The seam between an `AssumptionsRecord` and its typed `Assumptions` aggregate, plus minting and
listing.

All reads and writes of an assumptions set's data go through here, so no caller handles the raw JSON
dict -- the typed `Assumptions` is the only form the rest of the app sees. Like Plans (and unlike a
Profile), assumptions are not month-versioned: many labelled sets coexist per organization, and a
save overwrites the specific set being edited.
"""
from typing import Optional

from django.db.models import QuerySet

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from ..models import AssumptionsRecord
from .schemas import Assumptions


def load_assumptions( record: AssumptionsRecord ) -> Assumptions:
    return from_json_data( Assumptions, record.data )


def store_assumptions( record: AssumptionsRecord, assumptions: Assumptions ) -> None:
    record.data = to_json_data( assumptions )


def assumptions_for( organization: Organization ) -> QuerySet:
    """The organization's assumptions sets, most recent first."""
    return AssumptionsRecord.objects.filter(
        organization = organization ).order_by( '-created_datetime' )


def latest_assumptions( organization: Organization ) -> Optional[ AssumptionsRecord ]:
    """The organization's most recent assumptions set, or None if it has none."""
    return assumptions_for( organization ).first()


def save_assumptions(
        record: AssumptionsRecord, assumptions: Assumptions ) -> AssumptionsRecord:
    """Persist `assumptions` into `record` -- a specific set, with no monthly versioning."""
    store_assumptions( record, assumptions )
    record.save()
    return record


def create_assumptions( organization: Organization ) -> AssumptionsRecord:
    """Mint a new assumptions set for `organization` and return its record -- the single, extensible
    place that decides a new set's initial content and label."""
    record = AssumptionsRecord(
        organization = organization, label = _default_label( organization ) )
    return save_assumptions( record, _initial_assumptions() )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new set, since many coexist per organization."""
    return f'Assumptions {assumptions_for( organization ).count() + 1}'


def _initial_assumptions() -> Assumptions:
    """The content a new assumptions set starts from -- empty; the external-factors section seeds the
    economic-factors copy and tax forecast. The extension point for richer seeding later."""
    return Assumptions()
