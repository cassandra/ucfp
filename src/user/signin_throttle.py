"""
Sign-in abuse throttling: composes the general rate-limit primitive
(``common.rate_limit``) with sign-in-specific keys and limits.

Gated by ``settings.ABUSE_PREVENTION_ENABLED`` (off under tests and local dev),
so it is inert unless explicitly enabled. Limits read from settings of the same
name when present, else the defaults below -- so a deployment (or a test via
``@override_settings``) can tune any of them without code changes.
"""
import logging

from django.conf import settings
from django.http import HttpRequest

from common.rate_limit import check_rate_limit
from common.request_utils import get_client_ip

logger = logging.getLogger(__name__)

_HOUR_SECS = 60 * 60
_DAY_SECS  = 60 * 60 * 24

_LIMIT_DEFAULTS = {
    'SIGNIN_PER_IP_LIMIT'           : 10,   # requests per IP per hour
    'SIGNIN_PER_IP_WINDOW_SECS'     : _HOUR_SECS,
    'SIGNIN_PER_EMAIL_HOURLY_LIMIT' : 5,    # code sends per email per hour
    'SIGNIN_PER_EMAIL_DAILY_LIMIT'  : 10,   # code sends per email per day
    'SIGNIN_GLOBAL_LIMIT'           : 500,  # sign-in emails system-wide per hour
}


def _limit( name : str ) -> int:
    return getattr( settings, name, _LIMIT_DEFAULTS[ name ] )


def is_signin_request_allowed( request : HttpRequest, canonical_email : str ) -> bool:
    """Whether this sign-in POST may proceed to create an account and send a code.

    Enforces, in order, a per-IP request limit, per-email (hourly and daily) send
    caps, and a global sign-in-email ceiling. The checks short-circuit: a request
    already blocked by an earlier limit does not count against the later ones, so
    one throttled IP cannot inflate the global ceiling into a self-inflicted
    lockout. Returns True (allowed) when abuse prevention is disabled.
    """
    if not getattr( settings, 'ABUSE_PREVENTION_ENABLED', False ):
        return True

    client_ip = get_client_ip( request )
    is_allowed = (
        check_rate_limit( f'signin:ip:{client_ip}',
                          _limit( 'SIGNIN_PER_IP_LIMIT' ),
                          _limit( 'SIGNIN_PER_IP_WINDOW_SECS' ) )
        and check_rate_limit( f'signin:email-hour:{canonical_email}',
                              _limit( 'SIGNIN_PER_EMAIL_HOURLY_LIMIT' ),
                              _HOUR_SECS )
        and check_rate_limit( f'signin:email-day:{canonical_email}',
                              _limit( 'SIGNIN_PER_EMAIL_DAILY_LIMIT' ),
                              _DAY_SECS )
        and check_rate_limit( 'signin:global',
                              _limit( 'SIGNIN_GLOBAL_LIMIT' ),
                              _HOUR_SECS )
    )
    if not is_allowed:
        logger.info( 'Sign-in throttled: ip=%s email=%s', client_ip, canonical_email )
    return is_allowed
