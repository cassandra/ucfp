"""Template context for the onboarding surfaces."""
from ucfp.onboarding.membership import working_organization


def add_my_data_offer( request ):
    """Expose `offer_add_my_data` -- whether to promote "Add My Data" -- to every template. True when the
    user is signed in but has no organization of their own (the read-only sample, or nothing, is all they
    have), so their next step is to start their own plan. This is the single, encapsulated definition of
    the "early user" state, so its exact criteria (and any query cost) can be reworked in one place."""
    user = getattr( request, 'user', None )
    if ( user is None ) or ( not user.is_authenticated ):
        return { 'offer_add_my_data': False }
    return { 'offer_add_my_data': working_organization( user ) is None }
