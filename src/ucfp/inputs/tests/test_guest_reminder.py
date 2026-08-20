from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ucfp.inputs.mixins import GuestReminderMixin

User = get_user_model()


@override_settings(SUPPRESS_AUTHENTICATION=False)
class GuestReminderMixinTest(TestCase):
    """The decision behind the interview's 'save your work' reminder."""

    def setUp(self):
        self.mixin = GuestReminderMixin()
        return

    def _request_for(self, user):
        request = Mock()
        request.user = user
        request.organization = Mock()
        return request

    @patch('ucfp.inputs.mixins.completed_profile')
    def test_shows_for_a_guest_with_a_complete_profile(self, mock_completed_profile):
        mock_completed_profile.return_value = Mock()   # a complete profile record
        guest = User.objects.create_guest()
        self.assertTrue( self.mixin.show_guest_reminder( self._request_for( guest ) ) )

    @patch('ucfp.inputs.mixins.completed_profile')
    def test_hidden_until_the_profile_is_complete(self, mock_completed_profile):
        mock_completed_profile.return_value = None
        guest = User.objects.create_guest()
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( guest ) ) )

    @patch('ucfp.inputs.mixins.completed_profile')
    def test_hidden_for_a_verified_user(self, mock_completed_profile):
        mock_completed_profile.return_value = Mock()
        verified = User.objects.create_user( email = 'v@example.com' )
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( verified ) ) )

    @override_settings(SUPPRESS_AUTHENTICATION=True)
    @patch('ucfp.inputs.mixins.completed_profile')
    def test_hidden_under_suppressed_authentication(self, mock_completed_profile):
        # Self-hosted: the data is the server's, not browser-bound, so the reminder does not apply.
        mock_completed_profile.return_value = Mock()
        guest = User.objects.create_guest()
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( guest ) ) )
