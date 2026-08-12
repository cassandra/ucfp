import os

from django.conf import settings
from django.http import HttpRequest


def is_ajax( request : HttpRequest ):
    return bool( request.headers.get('x-requested-with') == 'XMLHttpRequest' )


def get_absolute_static_path( relative_path ):
    return os.path.join( settings.STATIC_URL, relative_path )


def get_client_ip( request : HttpRequest ) -> str:
    """The client IP as observed by the trusted reverse proxy (nginx).

    nginx sets ``X-Forwarded-For`` via ``$proxy_add_x_forwarded_for``, which
    **appends** the real peer to any client-supplied value -- so the **right-most**
    entry is the address nginx actually saw, while the left-most entries are
    attacker-controllable and must not be trusted for rate limiting. Take the
    right-most (this assumes a single trusted proxy hop); fall back to
    ``REMOTE_ADDR`` when there is no proxy (a direct/local connection)."""
    forwarded_for = request.headers.get( 'x-forwarded-for' )
    if forwarded_for:
        return forwarded_for.split( ',' )[ -1 ].strip()
    return request.META.get( 'REMOTE_ADDR', '' )
