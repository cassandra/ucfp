import logging
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from common.redis_client import get_redis_client
from user import signin_throttle

logging.disable(logging.CRITICAL)


@override_settings(
    ABUSE_PREVENTION_ENABLED=True,
    SIGNIN_PER_IP_LIMIT=1,
    SIGNIN_PER_EMAIL_HOURLY_LIMIT=100,
    SIGNIN_PER_EMAIL_DAILY_LIMIT=100,
    SIGNIN_GLOBAL_LIMIT=100,
)
class SigninThrottleTestCase(TestCase):

    def setUp(self):
        get_redis_client().flushdb()
        return

    def test_returns_the_first_failing_limit(self):
        self.assertIsNone( signin_throttle._first_tripped_limit( '1.2.3.4', 'e@x.test' ) )
        self.assertEqual( signin_throttle._first_tripped_limit( '1.2.3.4', 'e@x.test' ), 'per-ip' )

    def test_blocked_request_does_not_count_against_the_global_ceiling(self):
        # The one allowed request increments every counter, so global becomes 1.
        self.assertIsNone( signin_throttle._first_tripped_limit( '1.2.3.4', 'e@x.test' ) )
        # Every later request is blocked at per-IP and must not reach the global
        # counter -- else one throttled IP would inflate it into a global lockout.
        for _ in range( 5 ):
            self.assertEqual( signin_throttle._first_tripped_limit( '1.2.3.4', 'e@x.test' ), 'per-ip' )
        self.assertEqual( int( get_redis_client().get( 'ratelimit:signin:global' ) ), 1 )

    def test_alert_names_the_tripped_limit(self):
        request = RequestFactory().post( '/', HTTP_X_FORWARDED_FOR = '9.9.9.9' )
        signin_throttle.is_signin_request_allowed( request, 'e@x.test' )  # allowed
        with patch( 'user.signin_throttle.alert_admin' ) as mock_alert:
            signin_throttle.is_signin_request_allowed( request, 'e@x.test' )  # per-ip trip
        mock_alert.assert_called_once()
        self.assertEqual( mock_alert.call_args[ 0 ][ 0 ], 'signin-per-ip' )
