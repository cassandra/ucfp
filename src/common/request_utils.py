import os

from django.conf import settings
from django.http import HttpRequest


def is_ajax( request : HttpRequest ):
    return bool( request.headers.get('x-requested-with') == 'XMLHttpRequest' )


def get_absolute_static_path( relative_path ):
    return os.path.join( settings.STATIC_URL, relative_path )


def get_client_ip( request : HttpRequest ) -> str:
    """The originating client IP. Behind a reverse proxy (nginx) the real client
    is the left-most entry of the ``X-Forwarded-For`` list; fall back to
    ``REMOTE_ADDR`` when the header is absent (e.g. a direct/local connection)."""
    forwarded_for = request.headers.get( 'x-forwarded-for' )
    if forwarded_for:
        return forwarded_for.split( ',' )[ 0 ].strip()
    return request.META.get( 'REMOTE_ADDR', '' )
