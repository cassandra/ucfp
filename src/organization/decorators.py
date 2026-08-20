"""View decorators for resolving the current organization on a request, and gating writes to it."""
import functools

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone

from .capabilities import can_write
from .models import Organization, OrganizationMember
from .permissions import OrganizationPermissions

# HTTP methods that only read; they are never gated. Everything else (POST/PUT/PATCH/DELETE) is an
# unsafe method that a read-only member may not perform on organization data.
_SAFE_HTTP_METHODS = frozenset( { 'GET', 'HEAD', 'OPTIONS', 'TRACE' } )

# A view marked with this attribute (see `PermitsReadonlyMutation`) is exempt from the write-gate: a
# read-only member may perform its unsafe-method requests because it writes non-organization data.
_READONLY_MUTATION_ATTRIBUTE = 'permits_readonly_mutation'


class PermitsReadonlyMutation:
    """Mixin marking a view as exempt from the read-only write-gate.

    The default posture (see `ensure_organization`) denies a read-only member any unsafe-method
    request on the organization request path. A view that legitimately needs the current organization
    yet writes *non-organization* data mixes this in so a read-only member may still POST to it. Use
    sparingly -- the safe default is to deny.
    """
    permits_readonly_mutation = True


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
    ``SessionState`` (``request.session_state.current_organization_uuid``). Whether the member may
    modify it is attached as ``request.organization_can_write`` (a bool, also read by templates), and
    a read-only member's unsafe-method request is refused with ``PermissionDenied`` unless the view
    opts out (see `PermitsReadonlyMutation`) -- a fail-safe, default-deny write-gate.
    """
    @functools.wraps( view_func )
    def wrapped( request, *args, **kwargs ):
        request.organization = _resolve_current_organization( request )
        request.organization_can_write = _current_member_can_write( request )
        _enforce_write_access( request )
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


def _current_member_can_write( request ) -> bool:
    """Whether the request's member may modify the current organization's data (their role's
    `can_write`). A non-member -- which resolution does not produce -- is read-only."""
    membership = OrganizationPermissions.get_membership( request.user, request.organization )
    role = membership.organization_role if membership is not None else None
    return can_write( role )


def _enforce_write_access( request ):
    """Refuse a read-only member's unsafe-method request, unless the resolved view opts out.

    Default-deny: a read (safe method) always passes; a write passes only when the member `can_write`
    or the view is marked `PermitsReadonlyMutation`. A forgotten opt-out therefore fails toward denied.
    """
    if request.method in _SAFE_HTTP_METHODS:
        return
    if request.organization_can_write:
        return
    if _view_permits_readonly_mutation( request ):
        return
    raise PermissionDenied( 'This household is read-only for your role.' )


def _view_permits_readonly_mutation( request ) -> bool:
    """Whether the resolved view is marked exempt from the write-gate. Reads the marker from the
    resolved view (its class for a class-based view), which URL resolution has set by the time a view
    runs; unresolved requests (never the real path) are treated as not exempt."""
    view = getattr( getattr( request, 'resolver_match', None ), 'func', None )
    view_class = getattr( view, 'view_class', None )
    return bool( getattr( view, _READONLY_MUTATION_ATTRIBUTE, False )
                 or getattr( view_class, _READONLY_MUTATION_ATTRIBUTE, False ) )


def _resolve_current_organization( request ) -> Organization:
    state = request.session_state
    if state.current_organization_uuid is not None:
        membership = OrganizationMember.objects.active_membership_for(
            request.user, state.current_organization_uuid )
        if membership is not None:
            return membership.organization
    organization = _current_organization_for_request( request )
    state.set_current_organization( str( organization.uuid ) )
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
