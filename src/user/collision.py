"""The sign-in collision hand-off contract.

When the sign-in code determines that a signed-in Guest is about to become a *different* existing
account, it does not resolve that itself (reconciling the two plans is host-domain work). It stashes
the proven target here and redirects to ``settings.SIGNIN_COLLISION_URL``; the host's reconcile view
reads the target back through this module. Keeping the session key and its accessors here makes the
hand-off an explicit, one-way contract the host depends on -- not a bare string shared by convention.
"""
_COLLISION_TARGET_KEY = 'signin_collision_target'


def stash_collision_target( request, target ):
    """Record `target` (the existing account the Guest just proved they own) for the reconcile step."""
    request.session[ _COLLISION_TARGET_KEY ] = str( target.uuid )
    return


def peek_collision_target( request ):
    """The stashed target account uuid, or None -- read without clearing (the reconcile page renders
    on GET and resolves on POST)."""
    return request.session.get( _COLLISION_TARGET_KEY )


def clear_collision_target( request ):
    request.session.pop( _COLLISION_TARGET_KEY, None )
    return
