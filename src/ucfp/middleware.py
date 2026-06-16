import logging

from django.conf import settings
from django.core.exceptions import (
    BadRequest,
    ImproperlyConfigured,
    PermissionDenied,
    SuspiciousOperation,
)
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseNotAllowed,
    HttpResponseServerError,
)

from common.exceptions import MethodNotAllowedError

from . import views
from .session_state import SessionState

logger = logging.getLogger(__name__)


class SessionStateMiddleware:
    """
    Attaches the typed SessionState to every request as ``request.session_state``
    (parsed from the session), so views and templates read well-typed session
    state instead of ``request.session`` directly. Runs after Django's
    SessionMiddleware, which it depends on.
    """

    def __init__( self, get_response ):
        self.get_response = get_response
        return

    def __call__( self, request ):
        request.session_state = SessionState.from_session( request )
        return self.get_response( request )


class NoStoreMiddleware:
    """
    Set ``Cache-Control: no-store`` on dynamic HTML and JSON responses that
    don't already declare their own caching policy.

    Why on by default:
      - Privacy/security: with authentication enabled, rendered pages and AJAX
        JSON can carry per-user data that should not be written to the browser's
        disk cache (e.g. left on a shared machine, or shown by the back button
        after logout). ``no-store`` keeps dynamic responses out of cache.
      - Freshness: without an explicit directive, browsers apply heuristic
        caching to HTML and may serve a stale page. In an AJAX-driven UI this is
        especially deceptive -- a cached shell served while the server is
        unreachable looks functional but every request silently fails;
        ``no-store`` makes a reload-while-down show the browser's own error.

    Static assets (CSS/JS/images/fonts) are untouched -- their content types
    don't match and they should stay cacheable. Views that set their own
    ``Cache-Control`` (streaming endpoints, deliberately-cacheable public pages)
    are left alone, so a specific response can opt back into caching.

    Trade-off: ``no-store`` also disqualifies the back/forward cache (bfcache),
    so history navigation refetches. For a mostly-public, anonymous,
    content-heavy site, prefer scoping this to authenticated responses or
    dropping it.
    """

    _DYNAMIC_CONTENT_PREFIXES = ( 'text/html', 'application/json' )

    def __init__( self, get_response ):
        self.get_response = get_response
        return

    def __call__( self, request ):
        response = self.get_response( request )
        if response.has_header( 'Cache-Control' ):
            return response
        content_type = response.get( 'Content-Type', '' )
        for prefix in self._DYNAMIC_CONTENT_PREFIXES:
            if content_type.startswith( prefix ):
                response[ 'Cache-Control' ] = 'no-store'
                break
        return response


class ExceptionMiddleware:
    """
    Routes exceptions raised in views -- and bare Django error responses --
    through the project's rich error responses (an AJAX modal or a synchronous
    error page, decided per ``views.*_response`` helper by request type). This
    is what makes a ``raise BadRequest(...)`` / ``Http404`` / a view returning
    an ``HttpResponseNotAllowed``, or ``AsyncView``'s default-POST
    ``MethodNotAllowedError``, surface gracefully instead of as a bare 500.
    """

    def __init__( self, get_response ):
        self.get_response = get_response
        return

    def __call__( self, request ):
        return self.process_response( request, self.get_response( request ) )

    def process_exception( self, request, exception ):
        ip_address = request.headers.get( 'x-forwarded-for' )  # nginx forwarded
        logger.warning( f'Exception caught in middleware [{ip_address}]: {exception}' )

        if isinstance( exception, BadRequest ):
            return views.bad_request_response( request, message = str(exception) )
        if isinstance( exception, ImproperlyConfigured ):
            return views.improperly_configured_response( request, message = str(exception) )
        if isinstance( exception, SuspiciousOperation ):
            return views.bad_request_response( request, message = str(exception) )
        if isinstance( exception, PermissionDenied ):
            return views.not_authorized_response( request, message = str(exception) )
        if isinstance( exception, Http404 ):
            return views.page_not_found_response( request, message = str(exception) )
        if isinstance( exception, MethodNotAllowedError ):
            return views.method_not_allowed_response( request, message = str(exception) )

        logger.exception( f'Exception caught in middleware: {exception}' )
        return views.internal_error_response( request, message = str(exception) )

    def process_response( self, request, response ):

        if isinstance( response, HttpResponseBadRequest ):
            return views.bad_request_response( request )
        if isinstance( response, HttpResponseForbidden ):
            return views.not_authorized_response( request )
        if isinstance( response, HttpResponseNotFound ):
            # urls.py defines a custom 404 handler that emits a plain 404
            # response, so don't double up -- except under DEBUG, where Django
            # bypasses handler404 and returns its own HttpResponseNotFound.
            if settings.DEBUG:
                return views.page_not_found_response( request )
            return response
        if isinstance( response, HttpResponseNotAllowed ):
            return views.method_not_allowed_response( request )
        if isinstance( response, HttpResponseServerError ):
            logger.warning( 'Internal error in middleware' )
            return views.internal_error_response( request )
        return response
