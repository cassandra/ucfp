import logging
from unittest.mock import patch

from django.test import SimpleTestCase

from common import rate_limit
from common.redis_client import get_redis_client

logging.disable(logging.CRITICAL)


class CheckRateLimitTestCase(SimpleTestCase):

    def setUp(self):
        # fakeredis is one shared instance for the whole test run; start clean.
        get_redis_client().flushdb()
        return

    def test_allows_up_to_limit_then_blocks(self):
        allowed = [ rate_limit.check_rate_limit( 'k', limit = 3, window_secs = 60 )
                    for _ in range( 3 ) ]
        self.assertEqual( allowed, [ True, True, True ] )

        # The fourth hit in the same window is over the limit.
        self.assertFalse( rate_limit.check_rate_limit( 'k', limit = 3, window_secs = 60 ) )

    def test_distinct_keys_are_independent(self):
        self.assertTrue( rate_limit.check_rate_limit( 'a', limit = 1, window_secs = 60 ) )
        # 'a' is now exhausted, but 'b' has its own counter.
        self.assertFalse( rate_limit.check_rate_limit( 'a', limit = 1, window_secs = 60 ) )
        self.assertTrue( rate_limit.check_rate_limit( 'b', limit = 1, window_secs = 60 ) )

    def test_ttl_is_set_on_first_hit(self):
        rate_limit.check_rate_limit( 'k', limit = 5, window_secs = 90 )
        ttl = get_redis_client().ttl( 'ratelimit:k' )
        self.assertTrue( 0 < ttl <= 90 )

    def test_count_resets_after_window_expires(self):
        self.assertTrue( rate_limit.check_rate_limit( 'k', limit = 1, window_secs = 60 ) )
        self.assertFalse( rate_limit.check_rate_limit( 'k', limit = 1, window_secs = 60 ) )

        # Simulate the window elapsing by dropping the (TTL-bearing) key.
        get_redis_client().delete( 'ratelimit:k' )
        self.assertTrue( rate_limit.check_rate_limit( 'k', limit = 1, window_secs = 60 ) )

    def test_fails_open_when_redis_unavailable(self):
        with patch.object( rate_limit, 'get_redis_client', return_value = None ):
            allowed = [ rate_limit.check_rate_limit( 'k', limit = 1, window_secs = 60 )
                        for _ in range( 5 ) ]
        self.assertEqual( allowed, [ True ] * 5 )

    def test_fails_open_when_redis_errors(self):
        class _Boom:
            def incr(self, *args, **kwargs):
                raise RuntimeError( 'redis down' )

        with patch.object( rate_limit, 'get_redis_client', return_value = _Boom() ):
            self.assertTrue( rate_limit.check_rate_limit( 'k', limit = 1, window_secs = 60 ) )


class BackoffDelaySecsTestCase(SimpleTestCase):

    def test_free_attempts_incur_no_delay(self):
        delays = [ rate_limit.backoff_delay_secs( n, free_attempts = 2, first_delay = 1,
                                                  factor = 2, max_delay = 4 )
                   for n in range( 0, 3 ) ]
        self.assertEqual( delays, [ 0, 0, 0 ] )

    def test_delay_grows_geometrically_then_caps(self):
        schedule = [ rate_limit.backoff_delay_secs( n, free_attempts = 2, first_delay = 1,
                                                    factor = 2, max_delay = 4 )
                     for n in range( 3, 7 ) ]
        # attempts 3,4,5,6 -> 1, 2, 4, 4 (capped at max_delay)
        self.assertEqual( schedule, [ 1, 2, 4, 4 ] )
