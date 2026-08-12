"""
Per-session cooldown (with a per-IP backstop) for magic-code verification.

Slows and caps brute-forcing of the one-time code without an in-request sleep:
each wrong guess must wait an escalating cooldown before the next attempt, and
after a hard cap the code is invalidated so the attacker must start a fresh
sign-in. State is timestamp-based (no ``time.sleep``), so it never slows tests.

Per-session state lives in the raw ``request.session`` (as the code itself does)
-- deliberately not the domain-tier ``SessionState`` abstraction, to keep this
general auth code free of any dependency on the application layer. The per-IP
backstop uses the general Redis limiter to catch an attacker who cycles sessions
to dodge the per-session cooldown. Gated by ``settings.ABUSE_PREVENTION_ENABLED``.
"""
import logging

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from common.rate_limit import backoff_delay_secs, check_rate_limit
from common.request_utils import get_client_ip
from notify.admin_alert import alert_admin

logger = logging.getLogger(__name__)

_SESSION_FAILURES_KEY     = 'magic_code_failures'
_SESSION_NEXT_ALLOWED_KEY = 'magic_code_next_allowed_epoch'

_HOUR_SECS = 60 * 60

_DEFAULTS = {
    'SIGNIN_VERIFY_FREE_ATTEMPTS'    : 2,
    'SIGNIN_VERIFY_FIRST_DELAY_SECS' : 1,
    'SIGNIN_VERIFY_BACKOFF_FACTOR'   : 2,
    'SIGNIN_VERIFY_MAX_DELAY_SECS'   : 4,
    'SIGNIN_VERIFY_MAX_FAILURES'     : 5,
    'SIGNIN_VERIFY_PER_IP_LIMIT'     : 30,  # verify attempts per IP per hour
}


def _setting( name : str ) -> int:
    return getattr( settings, name, _DEFAULTS[ name ] )


def _now_epoch() -> int:
    return int( timezone.now().timestamp() )


def is_enabled() -> bool:
    return getattr( settings, 'ABUSE_PREVENTION_ENABLED', False )


def seconds_until_allowed( request : HttpRequest ) -> int:
    """Seconds remaining before the next attempt is permitted; 0 if now."""
    next_allowed_epoch = request.session.get( _SESSION_NEXT_ALLOWED_KEY, 0 )
    return max( 0, next_allowed_epoch - _now_epoch() )


def is_per_ip_backstop_ok( request : HttpRequest ) -> bool:
    """Record and check a verify attempt against the per-IP hourly backstop
    (fail-open via the underlying limiter). Alerts (coalesced) when it trips,
    since sustained verify attempts from one IP suggest brute-forcing."""
    client_ip = get_client_ip( request )
    is_ok = check_rate_limit( f'verify:ip:{client_ip}',
                              _setting( 'SIGNIN_VERIFY_PER_IP_LIMIT' ),
                              _HOUR_SECS )
    if not is_ok:
        logger.info( 'Verify per-IP backstop tripped: ip=%s', client_ip )
        alert_admin( 'verify-per-ip', f'Verify per-IP backstop tripped (ip={client_ip})' )
    return is_ok


def register_failure( request : HttpRequest ) -> int:
    """Record a wrong-code attempt and set the next-allowed time from the
    escalating backoff schedule. Returns the running failure count."""
    failure_count = request.session.get( _SESSION_FAILURES_KEY, 0 ) + 1
    delay_secs = backoff_delay_secs(
        failure_count,
        free_attempts = _setting( 'SIGNIN_VERIFY_FREE_ATTEMPTS' ),
        first_delay   = _setting( 'SIGNIN_VERIFY_FIRST_DELAY_SECS' ),
        factor        = _setting( 'SIGNIN_VERIFY_BACKOFF_FACTOR' ),
        max_delay     = _setting( 'SIGNIN_VERIFY_MAX_DELAY_SECS' ),
    )
    request.session[ _SESSION_FAILURES_KEY ] = failure_count
    request.session[ _SESSION_NEXT_ALLOWED_KEY ] = _now_epoch() + delay_secs
    return failure_count


def is_over_max_failures( failure_count : int ) -> bool:
    return failure_count >= _setting( 'SIGNIN_VERIFY_MAX_FAILURES' )


def reset( request : HttpRequest ):
    """Clear the per-session attempt state (on success or after invalidation)."""
    request.session.pop( _SESSION_FAILURES_KEY, None )
    request.session.pop( _SESSION_NEXT_ALLOWED_KEY, None )
    return
