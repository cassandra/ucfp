import logging
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from user import signin_cooldown

logging.disable(logging.CRITICAL)


@override_settings(
    ABUSE_PREVENTION_ENABLED=True,
    SIGNIN_VERIFY_FREE_ATTEMPTS=2,
    SIGNIN_VERIFY_FIRST_DELAY_SECS=1,
    SIGNIN_VERIFY_BACKOFF_FACTOR=2,
    SIGNIN_VERIFY_MAX_DELAY_SECS=4,
    SIGNIN_VERIFY_MAX_FAILURES=5,
)
class SigninCooldownTestCase(SimpleTestCase):

    def setUp(self):
        self.request = RequestFactory().post( '/' )
        self.request.session = {}
        return

    def test_free_attempts_incur_no_cooldown(self):
        with patch.object( signin_cooldown, '_now_epoch', return_value = 1000 ):
            signin_cooldown.register_failure( self.request )
            signin_cooldown.register_failure( self.request )
            self.assertEqual( signin_cooldown.seconds_until_allowed( self.request ), 0 )

    def test_cooldown_starts_and_elapses_after_free_attempts(self):
        with patch.object( signin_cooldown, '_now_epoch', return_value = 1000 ):
            for _ in range( 3 ):        # third failure -> first 1s cooldown
                signin_cooldown.register_failure( self.request )
            self.assertEqual( signin_cooldown.seconds_until_allowed( self.request ), 1 )
        with patch.object( signin_cooldown, '_now_epoch', return_value = 1001 ):
            self.assertEqual( signin_cooldown.seconds_until_allowed( self.request ), 0 )

    def test_delay_grows_then_caps_at_max(self):
        with patch.object( signin_cooldown, '_now_epoch', return_value = 1000 ):
            for _ in range( 6 ):        # 3->1, 4->2, 5->4, 6->4 (capped)
                signin_cooldown.register_failure( self.request )
            self.assertEqual( signin_cooldown.seconds_until_allowed( self.request ), 4 )

    def test_is_over_max_failures(self):
        self.assertFalse( signin_cooldown.is_over_max_failures( 4 ) )
        self.assertTrue( signin_cooldown.is_over_max_failures( 5 ) )

    def test_reset_clears_state(self):
        with patch.object( signin_cooldown, '_now_epoch', return_value = 1000 ):
            for _ in range( 4 ):
                signin_cooldown.register_failure( self.request )
        signin_cooldown.reset( self.request )
        self.assertEqual( signin_cooldown.seconds_until_allowed( self.request ), 0 )
        self.assertNotIn( 'magic_code_failures', self.request.session )
