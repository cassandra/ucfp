"""View decorators for resolving the current organization on a request."""
import functools

from django.http import Http404

from .models import Organization, OrganizationMember


def require_authenticated_user( view_func ):
    """Reject the request unless it carries a real authenticated user.

    Guards views that only make sense for a signed-in account (e.g. deleting that
    account or a household). When authentication is suppressed (self-hosted
    single-user) `request.user` is anonymous and these surfaces do not exist, so
    the request is answered with `Http404` rather than being allowed to act on a
    non-existent user. Under normal authentication the middleware has already
    ensured a user, so this is a no-op.
    """
    @functools.wraps( view_func )
    def wrapped( request, *args, **kwargs ):
        if not request.user.is_authenticated:
            raise Http404( 'No such page for an unauthenticated request.' )
        return view_func( request, *args, **kwargs )
    return wrapped


def ensure_organization( view_func ):
    """Guarantee a current organization before the view runs.

    A user must always belong to at least one organization, so this resolves one for the
    request (and persists it in the session, so later requests skip the work): it uses the
    organization already selected in the session, else the user's only one, else -- when they
    have none -- auto-provisions one they own (the `organization` app owns the creation and
    naming policy). Until multi-organization selection exists, a user with several raises rather
    than guess. An anonymous user -- which only occurs when authentication is suppressed
    (self-hosted single-user) -- resolves to the single shared, memberless organization.

    The resolved organization is attached as ``request.organization``; its uuid is stored via
    ``SessionState`` (``request.session_state.current_organization_uuid``).
    """
    @functools.wraps( view_func )
    def wrapped( request, *args, **kwargs ):
        request.organization = _resolve_current_organization( request )
        return view_func( request, *args, **kwargs )
    return wrapped


def _resolve_current_organization( request ) -> Organization:
    state = request.session_state
    if state.current_organization_uuid is not None:
        selected = Organization.objects.filter(
            uuid = state.current_organization_uuid ).first()
        if selected is not None:
            return selected
    organization = _current_organization_for_request( request )
    state.current_organization_uuid = str( organization.uuid )
    state.to_session( request )
    return organization


def _current_organization_for_request( request ) -> Organization:
    """The organization for the request: an authenticated user's own (auto-provisioned if they
    have none), or -- for an anonymous user, which only occurs when authentication is suppressed
    -- the single shared, memberless organization."""
    if not request.user.is_authenticated:
        return Organization.objects.get_or_create_shared()
    return _organization_for_user( request.user )


def _organization_for_user( user ) -> Organization:
    organizations = [ membership.organization
                      for membership in OrganizationMember.objects.for_user( user ) ]
    if not organizations:
        return Organization.objects.create_default_for_user( user )
    if len( organizations ) == 1:
        return organizations[ 0 ]
    raise NotImplementedError(
        'The user belongs to multiple organizations; selection is not yet supported.' )
