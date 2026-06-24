"""The seam between a `ProfileRecord` and its typed `Profile` aggregate, plus the monthly
save/retrieve policy.

All reads and writes of a profile's data go through here, so no caller handles the raw JSON
dict -- the typed `Profile` is the only form the rest of the app sees. This module also owns
the "at most one profile per month, retain prior months" policy and the canonical effective
date, so neither leaks into views or the schema.
"""
from datetime import date
from typing import Optional

from django.db.models import QuerySet
from django.utils import timezone

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from .models import ProfileRecord
from .schemas import Profile


def load_profile( record: ProfileRecord ) -> Profile:
    return from_json_data( Profile, record.data )


def store_profile( record: ProfileRecord, profile: Profile ) -> None:
    record.data = to_json_data( profile )


def current_effective_date() -> date:
    """The canonical effective date for a profile saved now -- the first of the current month.
    The monthly resolution policy lives here, not in the schema, so it can change without a
    migration."""
    return timezone.localdate().replace( day = 1 )


def profiles_for( organization: Organization ) -> QuerySet:
    """The organization's profiles, most recent effective date first."""
    return ProfileRecord.objects.filter(
        organization = organization ).order_by( '-effective_date', '-created_datetime' )


def latest_profile( organization: Organization ) -> Optional[ ProfileRecord ]:
    """The organization's most recent profile by effective date, or None if it has none."""
    return profiles_for( organization ).first()


def save_profile( organization: Organization, profile: Profile ) -> ProfileRecord:
    """Persist `profile` under the current month for `organization`: overwrite the current
    month's record if one exists, else create it -- leaving prior months untouched. At most one
    profile per month is enforced here rather than by a database constraint."""
    effective = current_effective_date()
    record = ProfileRecord.objects.filter(
        organization = organization, effective_date = effective ).first()
    if record is None:
        record = ProfileRecord(
            organization = organization, effective_date = effective,
            label = effective.strftime( '%B %Y' ) )
    store_profile( record, profile )
    record.save()
    return record


def create_profile( organization: Organization ) -> ProfileRecord:
    """Mint a new profile for `organization` and return its record -- the single, extensible
    place that decides a new profile's initial content."""
    return save_profile( organization, _initial_profile() )


def _initial_profile() -> Profile:
    """The content a newly created profile starts from -- empty for now; the extension point
    for pre-seeded defaults or carrying a prior month forward later."""
    return Profile()
