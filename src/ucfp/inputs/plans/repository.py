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

from ..enums import UsageRole
from ..models import PlansRecord
from ..naming import numbered_label, unique_label
from .schemas import Plans


def load_plans( record: PlansRecord ) -> Plans:
    return from_json_data( Plans, record.data )


def store_plans( record: PlansRecord, plans: Plans ) -> None:
    record.data = to_json_data( plans )


def plans_for( organization: Organization ) -> QuerySet:
    """The organization's SAVED plans, most recent first -- the WORKING copies backing an Explore sandbox
    (see `scenarios.repository`) are excluded, as they are not user-facing sets."""
    return PlansRecord.objects.filter(
        organization = organization, usage_role = str( UsageRole.SAVED ) ).order_by( '-created_datetime' )


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


def rename_plans( record: PlansRecord, label: str ) -> PlansRecord:
    """Rename a Plans set, leaving its contents untouched."""
    record.label = label
    record.save()
    return record


def clone_plans( record: PlansRecord, reviewed: bool = True ) -> PlansRecord:
    """Mint a new Plans set holding a copy of `record`'s contents, named "<label> copy" -- the basis for
    tweaking a variant without disturbing the original. The copy goes through the typed load/save seam, so
    it is fully independent of the source. When `reviewed` (the default, e.g. an Explore fork of an
    already-run set) it inherits the source's acknowledged sections; when not, it starts with none, so the
    user must walk each section to complete it -- the copied values are a starting point, not a finished
    set."""
    label = unique_label( f'{record.label} copy', plans_labels( record.organization ) )
    clone = PlansRecord(
        organization = record.organization, label = label,
        acknowledged_sections = list( record.acknowledged_sections ) if reviewed else list() )
    return save_plans( clone, load_plans( record ) )


def plans_labels( organization: Organization ) -> list:
    """The labels of the organization's SAVED Plans sets -- the taken names a new or copied set must avoid."""
    return [ record.label for record in plans_for( organization ) ]


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new set, since many coexist per organization."""
    return numbered_label( 'Plans', plans_labels( organization ) )


def _initial_plans() -> Plans:
    """The content a new Plans set starts from -- empty; the extension point for richer
    seeding later."""
    return Plans()
