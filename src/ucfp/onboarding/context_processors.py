"""Template context for the onboarding surfaces."""
from ucfp.onboarding.home_cta import HomeCtaState, home_cta_state


def add_my_data_offer( request ):
    """Expose `offer_add_my_data` -- whether to promote "Start planning" -- to every template. True for the
    early-user state: signed in, but the read-only example (or nothing) is all they have, so their next step
    is to start their own plan. Derived from `home_cta_state` (the EXAMPLE_ONLY state) so the criterion has a
    single home."""
    return { 'offer_add_my_data': home_cta_state( request ) == HomeCtaState.EXAMPLE_ONLY }
