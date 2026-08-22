"""The reserved sample organization and its relationship to a user's own organizations: the best-effort
auto-join that makes every new user a read-only VIEWER of the sample (so they can browse the sample-data
preview through the real read-only app), and the resolution/provisioning of the user's *own* working org
as distinct from that sample.

Auto-join is **best-effort**: if the sample org is not seeded (e.g. a self-hosted instance that never
seeded it), joining is a silent no-op so account creation is never broken by its absence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_UUID

if TYPE_CHECKING:
    from custom.models import CustomUser as UserType


def sample_organization():
    """The seeded sample organization, or None when it has not been seeded."""
    return Organization.objects.filter( uuid = SAMPLE_ORGANIZATION_UUID ).first()


def is_sample_organization( organization : 'Organization | None' ) -> bool:
    """Whether `organization` is the reserved read-only sample org. Useful where a prompt about *the
    user's own* data (saving it, adding to it) must not fire while they are merely viewing the sample."""
    return bool( organization ) and ( str( organization.uuid ) == str( SAMPLE_ORGANIZATION_UUID ) )


def join_sample_org( user : 'UserType' ) -> bool:
    """Idempotently make `user` a read-only VIEWER of the sample organization. Best-effort: a no-op
    returning False when the sample org is absent. Uses `get_or_create`, so it never duplicates a
    membership nor downgrades an existing one (e.g. the seed's superuser OWNER). Returns True when the
    user is (now or already) a member."""
    organization = sample_organization()
    if organization is None:
        return False
    organization.members.get_or_create(
        user = user, defaults = { 'organization_role': OrganizationRole.VIEWER } )
    return True


def working_organization( user : 'UserType' ) -> 'Organization | None':
    """The user's own working organization -- one they belong to *other than* the read-only sample org,
    preferring one they own -- or None when the sample (or nothing) is all they have. Their own data lives
    in a working org; the sample is a preview they only ever view, never a home. This is the single place
    the "does the user have more than the sample org?" question is answered -- it reuses the manager's
    landing policy, merely excluding the sample from consideration."""
    return OrganizationMember.objects.default_organization_for(
        user, exclude_uuids = ( SAMPLE_ORGANIZATION_UUID, ) )


def ensure_own_organization( request, user : 'UserType' ) -> 'Organization':
    """Ensure the user is in an organization of their own (not the sample), switching the session to it --
    creating a fresh owned one only when the sample (or nothing) is all they have. The one explicit
    provisioning point, called by "Add My Data" so a visitor graduates from previewing the sample to
    entering their own data."""
    organization = working_organization( user ) or Organization.objects.create_default_for_user( user )
    request.session_state.set_current_organization( str( organization.uuid ) )
    request.session_state.to_session( request )
    return organization
