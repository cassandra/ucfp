"""The reserved example organization and its relationship to a user's own organizations: the best-effort
auto-join that makes every new user a read-only VIEWER of the example (so they can browse the example-data
preview through the real read-only app), and the resolution/provisioning of the user's *own* working org
as distinct from that example.

Auto-join is **best-effort**: if the example org is not seeded (e.g. a self-hosted instance that never
seeded it), joining is a silent no-op so account creation is never broken by its absence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import EXAMPLE_ORGANIZATION_UUID

if TYPE_CHECKING:
    from custom.models import CustomUser as UserType


def example_organization():
    """The seeded example organization, or None when it has not been seeded."""
    return Organization.objects.filter( uuid = EXAMPLE_ORGANIZATION_UUID ).first()


def is_example_organization( organization : 'Organization | None' ) -> bool:
    """Whether `organization` is the reserved read-only example org. Useful where a prompt about *the
    user's own* data (saving it, adding to it) must not fire while they are merely viewing the example."""
    return bool( organization ) and ( str( organization.uuid ) == str( EXAMPLE_ORGANIZATION_UUID ) )


def join_example_org( user : 'UserType' ) -> bool:
    """Idempotently make `user` a read-only VIEWER of the example organization. Best-effort: a no-op
    returning False when the example org is absent. Uses `get_or_create`, so it never duplicates a
    membership nor downgrades an existing one (e.g. the seed's superuser OWNER). Returns True when the
    user is (now or already) a member."""
    organization = example_organization()
    if organization is None:
        return False
    organization.members.get_or_create(
        user = user, defaults = { 'organization_role': OrganizationRole.VIEWER } )
    return True


def working_organization( user : 'UserType' ) -> 'Organization | None':
    """The user's own working organization -- one they belong to *other than* the read-only example org,
    preferring one they own -- or None when the example (or nothing) is all they have. Their own data lives
    in a working org; the example is a preview they only ever view, never a home. This is the single place
    the "does the user have more than the example org?" question is answered -- it reuses the manager's
    landing policy, merely excluding the example from consideration."""
    return OrganizationMember.objects.default_organization_for(
        user, exclude_uuids = ( EXAMPLE_ORGANIZATION_UUID, ) )


def ensure_own_organization( request, user : 'UserType' ) -> 'Organization':
    """Ensure the session is on an organization of the user's own -- one they belong to other than the
    read-only example -- and return it. A valid non-example org already selected is *kept* (a deliberately
    chosen household is not disturbed); only when the current selection is the example, empty, or stale is it
    switched to the user's default own org, creating one when the example (or nothing) is all they have.
    Called wherever a visitor moves from previewing the example into their own data ("Add My Data", "Go to
    your dashboard")."""
    organization = ( _selected_own_organization( request, user )
                     or working_organization( user )
                     or Organization.objects.create_default_for_user( user ) )
    request.session_state.set_current_organization( str( organization.uuid ) )
    request.session_state.to_session( request )
    return organization


def _selected_own_organization( request, user : 'UserType' ) -> 'Organization | None':
    """The session's currently-selected organization when it is a real, non-example membership of `user` --
    an own org already in effect, which `ensure_own_organization` therefore leaves alone -- else None (the
    example org, no selection, or a stale one the user no longer belongs to)."""
    selected_uuid = request.session_state.current_organization_uuid
    if ( not selected_uuid ) or ( str( selected_uuid ) == str( EXAMPLE_ORGANIZATION_UUID ) ):
        return None
    membership = OrganizationMember.objects.filter(
        user = user, organization__uuid = selected_uuid ).select_related( 'organization' ).first()
    return membership.organization if membership else None
