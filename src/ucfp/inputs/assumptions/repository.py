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
from .defaults import default_assumptions
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


def delete_assumptions( record: AssumptionsRecord ) -> None:
    """Delete an assumptions set. Captured runs snapshot their inputs, so nothing downstream depends
    on it."""
    record.delete()


def rename_assumptions( record: AssumptionsRecord, label: str ) -> AssumptionsRecord:
    """Rename an assumptions set, leaving its contents untouched."""
    record.label = label
    record.save()
    return record


def clone_assumptions( record: AssumptionsRecord ) -> AssumptionsRecord:
    """Mint a new assumptions set holding a copy of `record`'s contents, named "<label> copy" -- the
    basis for tweaking a variant without disturbing the original. The copy goes through the typed
    load/save seam, so it is fully independent of the source."""
    clone = AssumptionsRecord(
        organization = record.organization, label = f'{record.label} copy' )
    return save_assumptions( clone, load_assumptions( record ) )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new set, since many coexist per organization."""
    return f'Assumptions {assumptions_for( organization ).count() + 1}'


def _initial_assumptions() -> Assumptions:
    """The content a new assumptions set starts from -- the default external factors (Expected economic
    outlook, COLA-indexed tax projection), so a minted set is complete and runnable and the
    external-factors section edits it rather than first populating it. The extension point for richer
    seeding later."""
    return default_assumptions()
