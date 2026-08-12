"""
Fail-open, Redis-backed rate-limiting primitives -- domain-agnostic.

Generic mechanisms with no knowledge of sign-in, users, email, or any
application term: callers supply opaque keys and limits. All Redis access goes
through ``common.redis_client``, and every check **fails open** (allows the
action) when Redis is unavailable or errors, so a cache outage never locks
legitimate users out.
"""
import logging

from .redis_client import get_redis_client

logger = logging.getLogger(__name__)

_RATE_LIMIT_KEY_NAMESPACE = 'ratelimit'


def check_rate_limit( key : str, limit : int, window_secs : int ) -> bool:
    """Record one hit against ``key`` and report whether it is still within
    ``limit`` for the current window.

    Fixed-window counter: the window's TTL is set on the first hit and never
    extended, so the count resets ``window_secs`` after that first hit
    regardless of continued traffic. Returns True (allowed) when Redis is
    unavailable or errors -- fail-open.
    """
    redis_client = get_redis_client()
    if redis_client is None:
        return True

    redis_key = f'{_RATE_LIMIT_KEY_NAMESPACE}:{key}'
    try:
        hit_count = redis_client.incr( redis_key )
        if hit_count == 1:
            redis_client.expire( redis_key, window_secs )
        return hit_count <= limit
    except Exception:
        logger.warning( 'Rate-limit check failed open for key=%s', key, exc_info = True )
        return True


def backoff_delay_secs( failure_count : int,
                        free_attempts : int = 0,
                        first_delay   : int = 1,
                        factor        : int = 2,
                        max_delay     : int = 60 ) -> int:
    """The cooldown a caller should enforce before the next attempt, given how
    many attempts have already failed.

    Pure and storage-agnostic: the caller persists ``failure_count`` and the
    resulting next-allowed time wherever it likes (session, Redis, ...). The
    first ``free_attempts`` failures incur no delay; after that the delay grows
    geometrically from ``first_delay`` by ``factor``, capped at ``max_delay``.
    """
    if failure_count <= free_attempts:
        return 0
    step = failure_count - free_attempts - 1
    delay = first_delay * ( factor ** step )
    return min( delay, max_delay )
