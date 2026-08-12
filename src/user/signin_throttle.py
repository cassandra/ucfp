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
from notify.admin_alert import alert_admin

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

    Enforces a per-IP request limit, per-email (hourly and daily) send caps, and a
    global sign-in-email ceiling (see ``_first_tripped_limit`` for the ordering and
    its rationale). On a block it logs and fires a coalesced admin alert naming the
    tripped limit. Returns True (allowed) when abuse prevention is disabled.
    """
    if not getattr( settings, 'ABUSE_PREVENTION_ENABLED', False ):
        return True

    client_ip = get_client_ip( request )
    tripped_limit = _first_tripped_limit( client_ip, canonical_email )
    if tripped_limit is None:
        return True

    logger.info( 'Sign-in throttled [%s]: ip=%s email=%s', tripped_limit, client_ip, canonical_email )
    alert_admin( f'signin-{tripped_limit}',
                 f'Sign-in rate limit "{tripped_limit}" tripped (ip={client_ip})' )
    return False


def _first_tripped_limit( client_ip : str, canonical_email : str ) -> str | None:
    """The name of the first limit this request exceeds, or None if within all.

    Checks run in order and stop at the first failure, so a request already over
    an earlier limit is not counted against the later ones -- one throttled IP
    cannot inflate the global ceiling into a self-inflicted lockout.
    """
    ordered_checks = [
        ( 'per-ip', f'signin:ip:{client_ip}',
          _limit( 'SIGNIN_PER_IP_LIMIT' ), _limit( 'SIGNIN_PER_IP_WINDOW_SECS' ) ),
        ( 'per-email-hour', f'signin:email-hour:{canonical_email}',
          _limit( 'SIGNIN_PER_EMAIL_HOURLY_LIMIT' ), _HOUR_SECS ),
        ( 'per-email-day', f'signin:email-day:{canonical_email}',
          _limit( 'SIGNIN_PER_EMAIL_DAILY_LIMIT' ), _DAY_SECS ),
        ( 'global', 'signin:global',
          _limit( 'SIGNIN_GLOBAL_LIMIT' ), _HOUR_SECS ),
    ]
    for limit_name, key, limit, window_secs in ordered_checks:
        if not check_rate_limit( key, limit, window_secs ):
            return limit_name
        continue
    return None
