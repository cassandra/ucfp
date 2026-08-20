import logging
from unittest.mock import Mock, patch

from custom.models import CustomUser
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from user.signin_manager import SigninManager
from testing.base_test_case import BaseTestCase

logging.disable(logging.CRITICAL)


class TestSigninManager(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.user = CustomUser.objects.create_user(
            email='test@example.com',
            password='testpass'
        )

    def test_signin_manager_singleton_behavior(self):
        self.assertIs( SigninManager(), SigninManager() )

    @patch('user.signin_manager.EmailSender')
    def test_send_magic_email_targets_the_account_and_carries_code_and_link(self, mock_email_sender_class):
        mock_email_sender = Mock()
        mock_email_sender_class.return_value = mock_email_sender

        request = self.factory.get('/account')
        request.META['HTTP_HOST'] = 'testserver'
        request.session = SessionStore()

        SigninManager().send_magic_email( request = request, user = self.user )

        mock_email_sender_class.assert_called_once()
        email_data = mock_email_sender_class.call_args[1]['data']
        self.assertEqual( email_data.to_email_address, self.user.email )
        self.assertIn( 'magic_code', email_data.template_context )
        self.assertIn( f'/user/magic/link/{self.user.uuid}/', email_data.template_context['page_url'] )
        # The code is bound to this account server-side (so it cannot be redirected onto another).
        self.assertEqual( request.session[ 'magic_code_target' ], str( self.user.uuid ) )
        mock_email_sender.send.assert_called_once()

    def test_send_magic_email_targets_the_pending_address_when_one_is_in_flight(self):
        guest = CustomUser.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )

        request = self.factory.get('/account')
        request.META['HTTP_HOST'] = 'testserver'
        request.session = SessionStore()

        with patch('user.signin_manager.EmailSender') as mock_email_sender_class:
            mock_email_sender_class.return_value = Mock()
            SigninManager().send_magic_email( request = request, user = guest )

        email_data = mock_email_sender_class.call_args[1]['data']
        self.assertEqual( email_data.to_email_address, 'claimed@example.com' )
