"""
Self-service account & household-data deletion (right to be forgotten).

Lives in the organization app because deletion is fundamentally organization-
aware: financial data is owned by the Organization (cascade), and the "at least
one active owner" invariant governs what may be removed. Organization may depend
on the user model; the reverse is not allowed, so this orchestration belongs
here rather than in the user app.

Sessions are an HTTP concern and are torn down by the calling view (logout);
these functions perform the data deletion only.
"""
from django.contrib.auth.models import User as UserType
from django.db import transaction

from .models import OrganizationMember


def account_deletion_disposition( user : UserType ):
    """How deleting ``user``'s account treats each of their organizations, grouped:

    - ``sole_owned`` -- deleted with their data; cannot be kept (leaving would
      orphan them).
    - ``co_owned`` -- deleted with their data **by default**, but the user may
      choose to keep each one for its other owners instead.
    - ``non_owned`` -- left intact; the user is removed but never owned the data.
    """
    memberships = list(
        OrganizationMember.objects.for_user( user ).select_related( 'organization' ) )
    sole_owned = [ m.organization for m in memberships if m.is_sole_active_owner ]
    co_owned   = [ m.organization for m in memberships if m.is_active_owner and not m.is_sole_active_owner ]
    non_owned  = [ m.organization for m in memberships if not m.is_active_owner ]
    return sole_owned, co_owned, non_owned


def delete_organization( organization ):
    """Permanently delete an organization and everything it owns.

    The organization's financial data (accounts, inputs, projection runs,
    parameter sets), its memberships, and its invitations all cascade away.
    """
    organization.delete()
    return


def leave_organization( member : OrganizationMember ):
    """Remove a user's membership without deleting the organization.

    Goes through ``OrganizationMember.delete()``, so an attempt to leave as the
    last active owner is refused (``LastActiveOwnerError``) -- a sole owner must
    delete the organization instead.
    """
    member.delete()
    return


def delete_account( user : UserType, keep_organization_uuids = () ):
    """Permanently delete ``user`` and the data that goes with them.

    By default **every organization the user owns** is deleted with its data.
    Pass ``keep_organization_uuids`` to preserve specific *co-owned* organizations
    (leaving them for their other owners) instead. A solely-owned organization is
    always deleted -- leaving it would orphan it -- and cannot be kept.

    Ordered so the last-active-owner invariant is never violated:

    1. Delete each owned organization that is not being kept -- this cascades its
       data and the user's membership in it.
    2. Remove the user's remaining memberships (kept co-owned organizations, and
       non-owned ones); each passes the guarded delete, leaving those organizations
       for their other members.
    3. Delete the user record itself.

    A naive ``user.delete()`` must never be used: the ``OrganizationMember.user``
    cascade bulk-deletes memberships and bypasses the owner-invariant guard,
    which would silently orphan any owned organization.
    """
    kept = { str( organization_uuid ) for organization_uuid in keep_organization_uuids }
    with transaction.atomic():
        owned_memberships = list(
            OrganizationMember.objects.for_user( user ).select_related( 'organization' ) )
        for member in owned_memberships:
            if not member.is_active_owner:
                continue
            if member.is_sole_active_owner or ( str( member.organization.uuid ) not in kept ):
                member.organization.delete()

        # Whatever memberships survive (kept co-owned, or non-owned) are safe for
        # the guarded row delete -- none is the last active owner of its org.
        for member in list( OrganizationMember.objects.filter( user = user ) ):
            member.delete()

        user.delete()
    return
