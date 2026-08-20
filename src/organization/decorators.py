"""View decorators for resolving the current organization on a request."""
import functools

from django.http import Http404
from django.utils import timezone

from .models import Organization, OrganizationMember


def require_authenticated_user( view_func ):
    """Reject the request with `Http404` unless it carries an authenticated user.

    Guards views that only exist for a signed-in account (deleting that account or a
    household). The gate is the absent user, not any deployment mode: with no user
    there is no such surface, so answering 404 is truthful rather than acting on a
    non-existent user. An anonymous request reaches a view only when
    `SUPPRESS_AUTHENTICATION` is set (typically a self-hosted single-user run).
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
    organization selected in the session when that is still one of the user's active
    memberships, else a default one (preferring an organization they own; see
    `OrganizationMemberManager.default_organization_for`), else -- when they have none --
    auto-provisions one they own (the `organization` app owns the creation and naming policy).
    Every request that reaches here carries a real user: a cloud account, or the
    self-hosted singleton Guest that `SelfHostedIdentityMiddleware` logs in under
    `SUPPRESS_AUTHENTICATION` (a cloud visitor with no account is held at the sign-in gate).

    The resolved organization is attached as ``request.organization``; its uuid is stored via
    ``SessionState`` (``request.session_state.current_organization_uuid``).
    """
    @functools.wraps( view_func )
    def wrapped( request, *args, **kwargs ):
        request.organization = _resolve_current_organization( request )
        # Render this request's datetimes in the household's timezone: activating it here means the
        # template `date` filter and `timezone.localtime()` (the run timestamps and the default run name)
        # all read the household's zone without threading it through each call site. Scoped to the view
        # (these views render eagerly) and always cleared, so it never leaks to another request's thread.
        timezone.activate( request.organization.tzinfo )
        try:
            return view_func( request, *args, **kwargs )
        finally:
            timezone.deactivate()
    return wrapped


def _resolve_current_organization( request ) -> Organization:
    state = request.session_state
    if state.current_organization_uuid is not None:
        membership = OrganizationMember.objects.active_membership_for(
            request.user, state.current_organization_uuid )
        if membership is not None:
            return membership.organization
    organization = _current_organization_for_request( request )
    state.current_organization_uuid = str( organization.uuid )
    state.to_session( request )
    return organization


def _current_organization_for_request( request ) -> Organization:
    """The organization for the request's (authenticated) user: their own, auto-provisioned if
    they have none. Both deployment modes reach here with a real user -- a cloud account, or the
    self-hosted singleton Guest logged in by `SelfHostedIdentityMiddleware`."""
    return _organization_for_user( request.user )


def _organization_for_user( user ) -> Organization:
    default = OrganizationMember.objects.default_organization_for( user )
    if default is not None:
        return default
    return Organization.objects.create_default_for_user( user )
