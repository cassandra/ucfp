"""View decorators for the user/account area."""
import functools

from organization.models import Organization, OrganizationMember


def ensure_organization( view_func ):
    """Guarantee a current organization before the view runs.

    A user must always belong to at least one organization, so this resolves one for the
    request (and persists it in the session, so later requests skip the work): it uses the
    organization already selected in the session, else the user's only one, else -- when they
    have none -- auto-provisions one they own (the `organization` app owns the creation and
    naming policy). Until multi-organization selection exists, a user with several raises rather
    than guess.

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
    organization = _organization_for_user( request.user )
    state.current_organization_uuid = str( organization.uuid )
    state.to_session( request )
    return organization


def _organization_for_user( user ) -> Organization:
    organizations = [ membership.organization
                      for membership in OrganizationMember.objects.for_user( user ) ]
    if not organizations:
        return Organization.objects.create_default_for_user( user )
    if len( organizations ) == 1:
        return organizations[ 0 ]
    raise NotImplementedError(
        'The user belongs to multiple organizations; selection is not yet supported.' )
