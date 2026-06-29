"""The seam between a `PlansRecord` and its typed `Plans` aggregate, plus minting and
listing.

All reads and writes of a plans's data go through here, so no caller handles the raw JSON
dict -- the typed `Plans` is the only form the rest of the app sees. Unlike a profile, a
plans is not month-versioned: many labelled plans coexist per organization, and a save
overwrites the specific plans being edited.
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
    """Persist `plans` into `record` -- a specific plans, with no monthly versioning."""
    store_plans( record, plans )
    record.save()
    return record


def create_plans( organization: Organization ) -> PlansRecord:
    """Mint a new plans for `organization` and return its record -- the single, extensible
    place that decides a new plans's initial content and label."""
    record = PlansRecord(
        organization = organization, label = _default_label( organization ) )
    return save_plans( record, _initial_plans() )


def _default_label( organization: Organization ) -> str:
    """A distinguishable default name for a new plans, since many coexist per organization."""
    return f'Plans {plans_for( organization ).count() + 1}'


def _initial_plans() -> Plans:
    """The content a new plans starts from -- the typed defaults (an Expected outlook, the
    general lifestyle scope); the extension point for richer seeding later."""
    return Plans()
