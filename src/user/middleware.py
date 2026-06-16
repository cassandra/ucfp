from django.conf import settings
from django.urls import Resolver404, resolve

from .views import UserSigninView


class AuthenticationMiddleware:
    """
    Requires an authenticated user for all views except a small allow-list of
    public endpoints (the signin flow itself, health, manifest/static helpers,
    the email unsubscribe landing, and the error pages). Unauthenticated
    requests to a protected view are answered with the signin page in place.

    The whole check is bypassed when ``settings.SUPPRESS_AUTHENTICATION`` is
    true -- the env-controlled switch for running with auth turned off.
    """

    EXEMPT_VIEW_URL_NAMES = {
        'manifest',
        'favicon',
        'home-javascript-files',
        'health',
        'notify_email_unsubscribe',
        'user_signin',
        'user_signin_magic_code',
        'user_signin_magic_link',
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

        return UserSigninView().get( request )
