"""Access to the reserved sample organization and the auto-join that makes every new user a read-only
VIEWER of it, so they can browse the sample-data preview through the real (read-only) app.

Auto-join is **best-effort**: if the sample org is not seeded (e.g. a self-hosted instance that never
seeded it), joining is a silent no-op so account creation is never broken by its absence.
"""
from organization.enums import OrganizationRole
from organization.models import Organization

from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_UUID


def sample_organization():
    """The seeded sample organization, or None when it has not been seeded."""
    return Organization.objects.filter( uuid = SAMPLE_ORGANIZATION_UUID ).first()


def join_sample_org( user ) -> bool:
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
