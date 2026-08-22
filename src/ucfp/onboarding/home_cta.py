"""The public home page's visitor-state resolution.

The home hero offers exactly one primary ("gold") action, and which one depends on where the visitor is
in onboarding. This module is the single, encapsulated place that decision is made, so the hero template
stays a straight branch on the state and the "one gold per state" rule has one home.
"""
from enum import Enum

from ucfp.onboarding.membership import working_organization


class HomeCtaState( Enum ):
    """The home hero's state for a visitor, ordered from cold to established. Each state fixes the single
    gold action the hero offers."""
    ANONYMOUS   = 'anonymous'      # no account yet
    SAMPLE_ONLY = 'sample_only'    # signed in, but the read-only sample (or nothing) is all they have
    OWN_ORG     = 'own_org'        # signed in with an organization of their own


def home_cta_state( request ) -> HomeCtaState:
    """Resolve the home hero's state for `request`: anonymous, a user whose only organization is the
    read-only sample, or a user with their own organization. The self-hosted singleton is always signed in
    and owns its organization, so it resolves to OWN_ORG. The single place the hero's one-gold-per-state
    rule is decided."""
    user = getattr( request, 'user', None )
    if ( user is None ) or ( not user.is_authenticated ):
        return HomeCtaState.ANONYMOUS
    if working_organization( user ) is None:
        return HomeCtaState.SAMPLE_ONLY
    return HomeCtaState.OWN_ORG
