"""The seam between a `ProfileRecord` and its typed `Profile` aggregate, plus the monthly
save/retrieve policy.

All reads and writes of a profile's data go through here, so no caller handles the raw JSON
dict -- the typed `Profile` is the only form the rest of the app sees. This module also owns
the "at most one profile per month, retain prior months" policy and the canonical effective
date, so neither leaks into views or the schema.

Advancing a *completed* profile into a new month is **explicit**, never a side effect of editing. A
completed month's record is an immutable snapshot retained as history (for later plan-vs-actual
comparison): `save_profile` never overwrites one -- its edits target the current month. The one
exception is a first, still-in-progress profile, which has no snapshot to protect and no history, so
it is built up in place (see `allow_profile_write_in_place`). Carrying an aged, completed profile
forward into the current month -- copying its facts and keeping only the non-decaying acknowledgments
so the volatile sections reopen for review -- is the explicit job of `advance_profile`.
`profile_is_outdated` is the date signal a surface gates on (with completeness) to require that advance.
"""
from datetime import date
from typing import Optional

from django.db.models import QuerySet
from django.utils import timezone

from common.dataclass_json import from_json_data, to_json_data

from organization.models import Organization

from ..interview import PROFILE_STICKY_SECTION_KEYS, profile_complete
from ..models import ProfileRecord
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


def allow_profile_write_in_place( organization: Organization ) -> bool:
    """Whether an edit may be written straight back onto the latest profile record, rather than a fresh
    current-month one. True only for a *first, still-in-progress* profile: it is incomplete (no finalized
    snapshot to protect) **and** the sole record (no earlier month exists as history). Any completed
    snapshot, or any profile with history, fails one clause -- its edits go to the current month, so a prior
    month is never overwritten. Incompleteness is judged by the *same* `profile_complete` the readiness gate
    uses -- so a walked-but-invalid profile (e.g. no housing choice yet) counts as in-progress here and is
    not stranded -- but completeness alone is not enough; the history clause is what makes the write safe."""
    latest = latest_profile( organization )
    if latest is None or profiles_for( organization ).count() != 1:
        return False
    return not profile_complete( load_profile( latest ), latest )


def save_profile( organization: Organization, profile: Profile ) -> ProfileRecord:
    """Persist `profile` for `organization`. A first, still-in-progress profile (see
    `allow_profile_write_in_place`) is written back in place -- and re-dated to the current month, since an
    unfinished profile's "as of" is simply now -- so building it across a month boundary neither strands the
    review state nor leaves it reading as outdated on completion. Otherwise the write targets the current
    month's record (minting it un-reviewed if absent): a completed snapshot is never overwritten, and a new
    month does not inherit a prior month's reviewed state -- carrying an aged profile forward is
    `advance_profile`'s explicit job. At most one profile per month is enforced here, not by a constraint."""
    effective = current_effective_date()
    if allow_profile_write_in_place( organization ):
        record = latest_profile( organization )
        record.effective_date = effective          # an in-progress profile tracks the present, no new record
        record.label          = effective.strftime( '%B %Y' )
    else:
        record = ProfileRecord.objects.filter(
            organization = organization, effective_date = effective ).first()
        if record is None:
            record = ProfileRecord(
                organization = organization, effective_date = effective,
                label = effective.strftime( '%B %Y' ) )
    store_profile( record, profile )
    record.save()
    return record


def advance_profile( organization: Organization ) -> ProfileRecord:
    """Advance `organization`'s profile into the current month -- the explicit "review/refresh the
    aged snapshot" action a surface routes to when `profile_is_outdated`. Mints a new current-month
    record carrying the latest month's facts forward, but keeping only the non-decaying (People)
    acknowledgments, so every volatile section reopens for review. The prior month's record is left
    intact as history. Idempotent: if a current-month record already exists it is returned unchanged,
    so acknowledging twice neither duplicates nor resets it."""
    effective = current_effective_date()
    existing  = ProfileRecord.objects.filter(
        organization = organization, effective_date = effective ).first()
    if existing is not None:
        return existing
    latest = latest_profile( organization )
    record = ProfileRecord(
        organization = organization, effective_date = effective,
        label = effective.strftime( '%B %Y' ),
        acknowledged_sections = _carried_acknowledgments( latest ) )
    store_profile( record, load_profile( latest ) if latest is not None else Profile() )
    record.save()
    return record


def _carried_acknowledgments( prior: Optional[ ProfileRecord ] ) -> list:
    """The acknowledgments an advanced record keeps from `prior` -- only the non-decaying (sticky)
    sections, so every volatile section reopens for review; empty when there is no prior month."""
    if prior is None:
        return []
    return sorted( prior.acknowledged_section_keys & PROFILE_STICKY_SECTION_KEYS )


def profile_is_outdated( organization: Organization ) -> bool:
    """Whether `organization`'s latest profile predates the current month -- the signal a surface gates
    on to require an explicit `advance_profile` (review/refresh) before running or editing. False when
    there is no profile yet: the empty case has its own create flow, not a refresh."""
    latest = latest_profile( organization )
    return latest is not None and latest.effective_date < current_effective_date()


def create_profile( organization: Organization ) -> ProfileRecord:
    """Mint a new profile for `organization` and return its record -- the single, extensible
    place that decides a new profile's initial content."""
    return save_profile( organization, _initial_profile() )


def _initial_profile() -> Profile:
    """The content a newly created profile starts from -- empty for now; the extension point
    for pre-seeded defaults or carrying a prior month forward later."""
    return Profile()
