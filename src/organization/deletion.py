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


def delete_account( user : UserType ):
    """Permanently delete ``user`` and the data that goes with them.

    Ordered so the last-active-owner invariant is never violated and no
    organization is left ownerless:

    1. Delete the organizations the user **solely owns** -- this cascades their
       data and the user's membership in them.
    2. Remove the user's remaining memberships (now all non-sole-owner, so each
       passes the guarded delete) -- co-owned and non-owned organizations are
       left intact for their other members.
    3. Delete the user record itself.

    A naive ``user.delete()`` must never be used: the ``OrganizationMember.user``
    cascade bulk-deletes memberships and bypasses the owner-invariant guard,
    which would silently orphan any solely-owned organization.
    """
    with transaction.atomic():
        active_memberships = list(
            OrganizationMember.objects.filter( user = user, is_active = True ) )
        for member in active_memberships:
            if member.is_sole_active_owner:
                member.organization.delete()

        # Whatever memberships survive the org deletions are non-sole-owner, so
        # the guarded row delete accepts them.
        for member in list( OrganizationMember.objects.filter( user = user ) ):
            member.delete()

        user.delete()
    return
