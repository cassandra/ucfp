"""
Edge-triggered alert coalescing -- domain-agnostic.

``should_alert`` returns True at most once per window per key, so a repeatedly
tripped condition notifies once per window instead of on every hit -- keeping an
alert from becoming its own flood. Backed by Redis (``common.redis_client``);
if Redis is unavailable it returns True (alert rather than silently swallow).
"""
import logging

from .redis_client import get_redis_client

logger = logging.getLogger(__name__)

_ALERT_KEY_NAMESPACE = 'alert'


def should_alert( key : str, window_secs : int ) -> bool:
    """True the first time ``key`` is seen within ``window_secs``, False for
    repeats in the same window -- an atomic once-per-window gate for coalescing
    alerts. Fails open (True) when Redis is unavailable or errors.
    """
    redis_client = get_redis_client()
    if redis_client is None:
        return True

    redis_key = f'{_ALERT_KEY_NAMESPACE}:{key}'
    try:
        was_first = redis_client.set( redis_key, '1', nx = True, ex = window_secs )
        return bool( was_first )
    except Exception:
        logger.warning( 'Alert coalesce check failed open for key=%s', key, exc_info = True )
        return True
