"""The visitor's onboarding state -- where a visitor sits on the path from stranger, to browsing the
read-only example, to an established user with their own plan.

This is a single, page-agnostic fact. Each public surface (home, the explanation, the tour) decides its
*own* labels and actions by branching on it, so the "where is this visitor?" question has one home while
the per-page CTA choices stay in the pages. It is distinct from `custom.user_state` (Anonymous / Guest /
Verified), which is the visitor's *identity*; this is their *progress toward a plan of their own*.
"""
from enum import Enum

from ucfp.onboarding.membership import working_organization


class OnboardingState( Enum ):
    """A visitor's onboarding state, ordered from cold to established. It names *where the visitor is*, not
    what any page offers them there."""
    ANONYMOUS    = 'anonymous'      # no account yet
    EXAMPLE_ONLY = 'example_only'   # signed in, but the read-only example (or nothing) is all they have
    OWN_ORG      = 'own_org'        # signed in with an organization of their own


def onboarding_state( request ) -> OnboardingState:
    """Resolve `request`'s onboarding state: anonymous, a user whose only organization is the read-only
    example, or a user with their own organization. The self-hosted singleton is always signed in and owns
    its organization, so it resolves to OWN_ORG. The single place this progression is decided."""
    user = getattr( request, 'user', None )
    if ( user is None ) or ( not user.is_authenticated ):
        return OnboardingState.ANONYMOUS
    if working_organization( user ) is None:
        return OnboardingState.EXAMPLE_ONLY
    return OnboardingState.OWN_ORG
