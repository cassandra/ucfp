"""Reconciling a Guest's in-progress plan with an existing account it collides with.

When a signed-in Guest (mid-plan) proves ownership of an email that already belongs to a *different*
verified account, we must not silently switch accounts and lose their work. This service supplies:

  - an `OrganizationSummary` of each side (household names + account balances) to tell the plans apart,
    and the `has_content` test that decides whether a Guest even has a plan worth keeping;
  - the two resolutions -- keep the current work (re-home it onto the existing account) or discard it
    (keep the existing account's plan) -- each dropping the superseded Guest and orphaning the losing
    organization (its rows retained, ownerless, rather than destroyed).

It reads a Profile (`ucfp.inputs`) and rewrites organization ownership (`organization`); the view owns
all HTTP/session/login handling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.profile.repository import latest_profile, load_profile

if TYPE_CHECKING:
    # The project's user model, for annotations only -- these accounts are `CustomUser`
    # (not Django's `User`), which carries the is_guest/verify_pending_email/uuid API this uses.
    from custom.models import CustomUser as UserType


@dataclass
class OrganizationSummary:
    """The few identifying facts that distinguish one plan from another at a glance -- the household
    members' names and the funded accounts (name + opening balance). Empty on both counts means there
    is nothing of substance, so the plan is treated as absent."""
    subject_names : list[ str ]                   = field( default_factory = list )
    accounts      : list[ tuple[ str, Decimal ] ] = field( default_factory = list )

    @property
    def has_content( self ) -> bool:
        return bool( self.subject_names or self.accounts )


def organization_summary( organization : Organization ) -> OrganizationSummary:
    """`organization`'s latest Profile reduced to its identifying facts: named household members and
    accounts carrying a non-zero opening balance. No profile summarizes to empty."""
    record = latest_profile( organization )
    if record is None:
        return OrganizationSummary()
    profile = load_profile( record )
    subject_names = [ subject.name.strip() for subject in profile.subjects if subject.name.strip() ]
    accounts = [ ( asset.name.strip() or asset.handle, asset.opening_value )
                 for asset in profile.assets if asset.opening_value ]
    return OrganizationSummary( subject_names = subject_names, accounts = accounts )


def sole_organization( user : UserType ) -> Organization:
    """The single organization `user` belongs to. Guests and freshly-verified accounts own exactly
    one; this returns the first active membership's organization."""
    membership = OrganizationMember.objects.for_user( user ).select_related( 'organization' ).first()
    if membership is None:
        # The "exactly one organization" invariant is broken -- fail loudly here rather than let a
        # `None` dereference surface as an opaque AttributeError deep in the reconcile transaction.
        raise RuntimeError( f'Account {user.pk} belongs to no organization; reconcile assumes exactly one.' )
    return membership.organization


@transaction.atomic
def keep_current_discard_previous( guest : UserType, target : UserType ):
    """Re-home the Guest's plan onto `target`: `target` becomes sole owner of the Guest's organization,
    its own previous organization is orphaned (retained, ownerless), and the Guest account is removed.
    `target` ends owning exactly one organization -- the Guest's work."""
    guest_organization = sole_organization( guest )
    previous_organization = sole_organization( target )
    _transfer_sole_ownership( guest_organization, target )
    _orphan_organization( previous_organization )
    guest.delete()
    return


@transaction.atomic
def discard_current_keep_previous( guest : UserType, target : UserType ):
    """Keep `target`'s existing plan and drop the Guest: the Guest's organization is orphaned
    (retained, ownerless) and the Guest account removed. `target` is untouched here (nothing moves onto
    it) but kept in the signature for symmetry with `keep_current_discard_previous`, so the two
    resolutions are called the same way."""
    _orphan_organization( sole_organization( guest ) )
    guest.delete()
    return


def _transfer_sole_ownership( organization : Organization, to_user : UserType ):
    # Replace every membership with a single owning one. The bulk delete deliberately bypasses the
    # last-owner guard (a Model.delete() hook) -- we are re-owning the organization, not orphaning it.
    organization.members.all().delete()
    organization.members.create( user = to_user, organization_role = OrganizationRole.OWNER )
    return


def _orphan_organization( organization : Organization ):
    # Drop all memberships (bulk delete bypasses the last-owner guard), leaving the organization and
    # its data intact but ownerless -- recoverable, not destroyed.
    organization.members.all().delete()
    return
