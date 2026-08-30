"""Template context for the onboarding surfaces."""
from ucfp.onboarding.state import OnboardingState, onboarding_state


def onboarding_context( request ):
    """Expose the visitor's onboarding state to every template, so the public surfaces (home, the
    explanation, the tour) can each branch to their own CTA off one shared fact:

      - `onboarding_state` -- the state's value (`anonymous` / `example_only` / `own_org`), the general
        "where is this visitor?" fact each page reads to choose its own labels and actions;
      - `offer_add_my_data` -- the derived early-user flag (only the read-only example, or nothing, is
        theirs) that the "Start planning" banners consume, kept so that criterion has a single home.
    """
    state = onboarding_state( request )
    return {
        'onboarding_state' : state.value,
        'offer_add_my_data': state == OnboardingState.EXAMPLE_ONLY,
    }
