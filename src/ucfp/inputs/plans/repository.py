"""The seam between a `PlansRecord` and its typed `Plans` aggregate, plus minting and
listing.

All reads and writes of a Plans set's data go through here, so no caller handles the raw JSON
dict -- the typed `Plans` is the only form the rest of the app sees. Unlike a profile, a Plans
set is not month-versioned: many labelled sets coexist per organization, and a save overwrites
the specific set being edited.
"""
from typing import Optional

from django.db.models import QuerySet

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from ..models import PlansRecord
from .schemas import Plans


def load_plans( record: PlansRecord ) -> Plans:
    return from_json_data( Plans, record.data )


def store_plans( record: PlansRecord, plans: Plans ) -> None:
    record.data = to_json_data( plans )


def plans_for( organization: Organization ) -> QuerySet:
    """The organization's plans, most recent first."""
    return PlansRecord.objects.filter(
        organization = organization ).order_by( '-created_datetime' )


def latest_plans( organization: Organization ) -> Optional[ PlansRecord ]:
    """The organization's most recent plans, or None if it has none."""
    return plans_for( organization ).first()


def save_plans( record: PlansRecord, plans: Plans ) -> PlansRecord:
    """Persist `plans` into `record` -- a specific set, with no monthly versioning."""
    store_plans( record, plans )
    record.save()
    return record


def create_plans( organization: Organization ) -> PlansRecord:
    """Mint a new Plans set for `organization` and return its record -- the single, extensible
    place that decides a new set's initial content and label."""
    record = PlansRecord(
        organization = organization, label = _default_label( organization ) )
    return save_plans( record, _initial_plans() )


def delete_plans( record: PlansRecord ) -> None:
    """Delete a Plans set. Captured runs snapshot their inputs, so nothing downstream depends on it."""
    record.delete()


def rename_plans( record: PlansRecord, label: str ) -> PlansRecord:
    """Rename a Plans set, leaving its contents untouched."""
    record.label = label
    record.save()
    return record


def clone_plans( record: PlansRecord ) -> PlansRecord:
    """Mint a new Plans set holding a copy of `record`'s contents, named "<label> copy" -- the basis
    for tweaking a variant without disturbing the original. The copy goes through the typed load/save
    seam, so it is fully independent of the source."""
    clone = PlansRecord( organization = record.organization, label = f'{record.label} copy' )
    return save_plans( clone, load_plans( record ) )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new set, since many coexist per organization."""
    return f'Plans {plans_for( organization ).count() + 1}'


def _initial_plans() -> Plans:
    """The content a new Plans set starts from -- empty; the extension point for richer
    seeding later."""
    return Plans()
