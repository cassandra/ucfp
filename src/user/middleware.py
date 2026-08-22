from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import Resolver404, resolve, reverse

from organization.models import Organization

from .signin_manager import SigninManager


class SelfHostedIdentityMiddleware:
    """Give the self-hosted single-user deployment a real (Guest) identity.

    When ``SUPPRESS_AUTHENTICATION`` is set there is no sign-in; rather than run each request
    as an anonymous user on a special shared organization, we log the request in as the
    singleton self-hosted Guest (created on first use). Downstream code then sees a normal
    authenticated user owning a normal organization -- one identity model instead of an
    anonymous special case. Inert when authentication is enforced (the cloud deployment).

    Ordered after Django's ``AuthenticationMiddleware`` (which populates ``request.user`` from
    the session) and before ``AuthenticationMiddleware`` below (the sign-in gate), so by the
    time the gate runs the self-hosted request already carries its user.
    """

    def __init__( self, get_response ):
        self.get_response = get_response
        return

    def __call__( self, request ):
        if settings.SUPPRESS_AUTHENTICATION and not request.user.is_authenticated:
            request.user = Organization.objects.get_or_create_self_hosted_owner()
            SigninManager().do_login( request = request )
        return self.get_response( request )


class AuthenticationMiddleware:
    """
    Requires an authenticated user for all views except a small allow-list of
    public endpoints (the signin flow itself, health, manifest/static helpers,
    the onboarding pages, the email unsubscribe landing, and the error pages).
    An unauthenticated request to a protected view is redirected to the public
    home page -- the funnel into onboarding -- rather than confronted with a
    sign-in form it did not ask for.

    The whole check is bypassed when ``settings.SUPPRESS_AUTHENTICATION`` is
    true -- the env-controlled switch for running with auth turned off.
    """

    EXEMPT_VIEW_URL_NAMES = {
        'manifest',
        'favicon',
        'home-javascript-files',
        'health',
        'home',
        'home_index',
        'about',
        'contact',
        'privacy',
        'terms',
        'notify_email_unsubscribe',
        'notify_email_resubscribe',
        'privacy_accept',
        'explain',
        'preview',
        'convert_to_guest',
        'start_tour',
        'add_my_data',
        'user_signin',
        'magic_code',
        'magic_link',
        'bad_request',
        'not_authorized',
        'page_not_found',
        'method_not_allowed',
        'internal_error',
        'transient_error',
    }

    def __init__( self, get_response ):
        self.get_response = get_response
        return

    def __call__( self, request ):

        if settings.SUPPRESS_AUTHENTICATION or request.user.is_authenticated:
            return self.get_response( request )

        try:
            resolver_match = resolve( request.path )
        except Resolver404:
            return self.get_response( request )

        if (( resolver_match.app_name == 'admin' )
                or ( resolver_match.url_name in self.EXEMPT_VIEW_URL_NAMES )):
            return self.get_response( request )

        return HttpResponseRedirect( reverse( 'home' ) )
