"""View decorators gating on a user's account state (see `custom.user_state`).

This lives in `custom` -- the lowest shared layer -- so every app can gate on it without an import
cycle, and it stays self-contained (it raises rather than referencing any app's URLs).
"""
import functools

from django.http import Http404


def require_verified_user( view_func ):
    """Reject the request with `Http404` unless it carries a Verified user.

    The gate for features reserved to a Verified account -- inviting others, managing additional
    organizations, and the like -- so a Guest is never *implicitly* granted them just by being signed
    in. It is a hard backstop; a template should also hide such a control from a Guest, branching on
    `request.user.is_verified`. A Guest and an anonymous request are treated identically (404), so a
    gated feature is not even revealed to a user who cannot use it.
    """
    @functools.wraps( view_func )
    def wrapped( request, *args, **kwargs ):
        if not ( request.user.is_authenticated and request.user.is_verified ):
            raise Http404( 'No such page for a user without a verified account.' )
        return view_func( request, *args, **kwargs )
    return wrapped
