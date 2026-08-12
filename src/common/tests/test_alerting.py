import logging
from unittest.mock import patch

from django.test import SimpleTestCase

from common import alerting
from common.redis_client import get_redis_client

logging.disable(logging.CRITICAL)


class ShouldAlertTestCase(SimpleTestCase):

    def setUp(self):
        # fakeredis is one shared instance for the whole test run; start clean.
        get_redis_client().flushdb()
        return

    def test_emits_once_then_coalesces_within_window(self):
        first = alerting.should_alert( 'limit-tripped', window_secs = 3600 )
        repeats = [ alerting.should_alert( 'limit-tripped', window_secs = 3600 )
                    for _ in range( 4 ) ]
        self.assertTrue( first )
        self.assertEqual( repeats, [ False, False, False, False ] )

    def test_distinct_keys_alert_independently(self):
        self.assertTrue( alerting.should_alert( 'per-ip', window_secs = 3600 ) )
        self.assertTrue( alerting.should_alert( 'per-email', window_secs = 3600 ) )
        self.assertFalse( alerting.should_alert( 'per-ip', window_secs = 3600 ) )

    def test_alerts_again_after_window_expires(self):
        self.assertTrue( alerting.should_alert( 'k', window_secs = 3600 ) )
        self.assertFalse( alerting.should_alert( 'k', window_secs = 3600 ) )

        # Simulate the coalesce window elapsing by dropping the key.
        get_redis_client().delete( 'alert:k' )
        self.assertTrue( alerting.should_alert( 'k', window_secs = 3600 ) )

    def test_fails_open_when_redis_unavailable(self):
        with patch.object( alerting, 'get_redis_client', return_value = None ):
            self.assertTrue( alerting.should_alert( 'k', window_secs = 3600 ) )
            # Without Redis it cannot coalesce, so it alerts rather than swallow.
            self.assertTrue( alerting.should_alert( 'k', window_secs = 3600 ) )
