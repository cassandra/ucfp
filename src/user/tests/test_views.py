import logging
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.http import HttpResponse
from django.test import override_settings
from django.urls import reverse

from common.redis_client import get_redis_client
from notify.email_sender import EmailSender
from user.magic_code_generator import MagicCodeStatus, MagicCodeGenerator
from user.signin_manager import SigninManager
from testing.view_test_base import SyncViewTestCase

logging.disable(logging.CRITICAL)

User = get_user_model()


class TestUserSigninView(SyncViewTestCase):
    """
    Tests for UserSigninView - demonstrates user authentication testing.
    This view handles email-based signin requests.
    """

    def setUp(self):
        super().setUp()
        # Use the user from parent setUp()

    @patch.object(EmailSender, 'is_email_configured')
    def test_get_signin_page_email_configured(self, mock_is_configured):
        """Test getting signin page when email is configured."""
        mock_is_configured.return_value = True

        url = reverse('user_signin')
        response = self.client.get(url)

        self.assertSuccessResponse(response)
        self.assertHtmlResponse(response)
        self.assertTemplateRendered(response, 'user/pages/signin.html')
        self.assertEqual(response.context['email_not_configured'], False)

    @patch.object(EmailSender, 'is_email_configured')
    def test_get_signin_page_email_not_configured(self, mock_is_configured):
        """Test getting signin page when email is not configured."""
        mock_is_configured.return_value = False

        url = reverse('user_signin')
        response = self.client.get(url)

        self.assertSuccessResponse(response)
        self.assertEqual(response.context['email_not_configured'], True)

    def test_get_signin_already_authenticated_redirects_home(self):
        """An authenticated user has no sign-in step to complete; GET redirects home."""
        self.client.force_login(self.user)

        url = reverse('user_signin')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_post_signin_already_authenticated_redirects_home(self):
        """An authenticated user posting the sign-in form is redirected home, not errored."""
        self.client.force_login(self.user)

        url = reverse('user_signin')
        response = self.client.post(url, {'email': 'test@example.com'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_post_signin_no_email(self):
        """Test POST request without email."""
        url = reverse('user_signin')
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, 400)

    def test_post_signin_invalid_email(self):
        """Test POST request with invalid email."""
        url = reverse('user_signin')
        response = self.client.post(url, {'email': 'invalid-email'})

        self.assertEqual(response.status_code, 400)

    @patch('user.views.SendMagicLinkEmailView')
    def test_post_signin_existing_user(self, mock_send_view_class):
        """Test POST request with existing user email."""
        from django.http import HttpResponse
        mock_send_view = mock_send_view_class.return_value
        mock_send_view.send_signin_magic_link.return_value = HttpResponse('mock_response')

        url = reverse('user_signin')
        _ = self.client.post(url, {'email': self.user.email})

        # Should delegate to SendMagicLinkEmailView
        mock_send_view.send_signin_magic_link.assert_called_once()
        call_kwargs = mock_send_view.send_signin_magic_link.call_args[1]
        self.assertEqual(call_kwargs['override_user'], self.user)

    @patch('user.views.SendMagicLinkEmailView')
    def test_post_signin_unknown_email_creates_user(self, mock_send_view_class):
        """An unknown email creates a new account and proceeds to send a code."""
        from django.http import HttpResponse
        mock_send_view = mock_send_view_class.return_value
        mock_send_view.send_signin_magic_link.return_value = HttpResponse('mock_response')

        new_email = 'newcomer@example.com'
        self.assertFalse(User.objects.filter(email=new_email).exists())

        url = reverse('user_signin')
        _ = self.client.post(url, {'email': new_email})

        # The previously-unknown email now has an account...
        created_user = User.objects.get(email=new_email)
        # ...and the flow proceeds to send a sign-in code for that user.
        mock_send_view.send_signin_magic_link.assert_called_once()
        call_kwargs = mock_send_view.send_signin_magic_link.call_args[1]
        self.assertEqual(call_kwargs['override_user'], created_user)

    @patch('user.views.SendMagicLinkEmailView')
    def test_post_signin_canonicalizes_email_case(self, mock_send_view_class):
        """Mixed-case variants of one address resolve to a single account."""
        from django.http import HttpResponse
        mock_send_view = mock_send_view_class.return_value
        mock_send_view.send_signin_magic_link.return_value = HttpResponse('mock_response')

        url = reverse('user_signin')
        self.client.post(url, {'email': 'Mixed.Case@Example.COM'})
        self.client.post(url, {'email': 'mixed.case@example.com'})

        self.assertEqual(User.objects.filter(email='mixed.case@example.com').count(), 1)
        self.assertFalse(User.objects.filter(email='Mixed.Case@Example.COM').exists())

    def test_post_signin_email_validation_error(self):
        """Test POST request with email that fails validation."""
        url = reverse('user_signin')
        # Pass actually invalid email format that will fail Django's validate_email
        response = self.client.post(url, {'email': 'not-an-email'})

        self.assertEqual(response.status_code, 400)

    def test_post_signin_unsubscribed_email_offers_resubscribe(self):
        """A sign-in for an unsubscribed address surfaces the re-enable path
        instead of silently dead-ending (the code email is suppressed)."""
        from notify.models import UnsubscribedEmail
        UnsubscribedEmail.objects.create(email=self.user.email)

        response = self.client.post(reverse('user_signin'), {'email': self.user.email})

        self.assertTemplateRendered(response, 'user/pages/signin_unsubscribed.html')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST='smtp.example.com', EMAIL_PORT=587, EMAIL_HOST_USER='u',
        DEFAULT_FROM_EMAIL='from@example.com', SERVER_EMAIL='srv@example.com',
    )
    def test_real_signin_code_email_carries_list_unsubscribe_header(self):
        """The genuine sign-in code email (not a synthetic send) carries the
        one-click List-Unsubscribe headers -- the deliverability contract."""
        from django.core import mail

        self.client.post(reverse('user_signin'), {'email': 'fresh@example.com'})

        self.assertEqual(len(mail.outbox), 1)
        headers = mail.outbox[0].extra_headers
        self.assertIn('List-Unsubscribe', headers)
        self.assertEqual(headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')


class TestSendMagicLinkEmailView(SyncViewTestCase):
    """
    Tests for SendMagicLinkEmailView - demonstrates magic link email testing.
    This view sends magic link emails for authentication.
    """

    def setUp(self):
        super().setUp()
        # Use the user from parent setUp()

    @patch.object(SigninManager, 'send_signin_magic_link_email')
    @patch('user.views.SigninMagicCodeView')
    def test_send_signin_magic_link(self, mock_magic_code_view_class, mock_send_email):
        """Test sending signin magic link email."""
        mock_magic_code_view = mock_magic_code_view_class.return_value
        mock_magic_code_view.get_response.return_value = 'mock_response'

        from user.views import SendMagicLinkEmailView
        view = SendMagicLinkEmailView()

        # Create a mock request
        request = self.client.get('/').wsgi_request

        _ = view.send_signin_magic_link(
            request=request,
            override_user=self.user
        )

        # Should call signin manager to send email
        mock_send_email.assert_called_once()

        # Should delegate to magic code view for response
        mock_magic_code_view.get_response.assert_called_once()

    @patch.object(SigninManager, 'send_signin_magic_link_email')
    @patch('user.views.SigninMagicCodeView')
    def test_send_magic_link_creates_user_auth_data(self, mock_magic_code_view_class, mock_send_email):
        """Test that user authentication data is created properly."""
        mock_magic_code_view = mock_magic_code_view_class.return_value
        mock_magic_code_view.get_response.return_value = 'mock_response'

        from user.views import SendMagicLinkEmailView
        view = SendMagicLinkEmailView()

        # Create a mock request
        request = self.client.get('/').wsgi_request

        view.send_signin_magic_link(
            request=request,
            override_user=self.user
        )

        # Should pass user auth data to signin manager
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args[1]
        self.assertIn('user_auth_data', call_args)


class TestSigninMagicCodeView(SyncViewTestCase):
    """
    Tests for SigninMagicCodeView - demonstrates magic code verification testing.
    This view handles magic code form submission and verification.
    """

    def setUp(self):
        super().setUp()
        # Use the user from parent setUp()

    def test_get_response_method(self):
        """Test the get_response method renders correctly."""
        from user.views import SigninMagicCodeView
        from user.forms import SigninMagicCodeForm

        view = SigninMagicCodeView()
        form = SigninMagicCodeForm(initial={'email_address': 'test@example.com'})

        # Create a mock request
        request = self.client.get('/').wsgi_request

        response = view.get_response(request=request, magic_code_form=form)

        # Should render the magic code template
        self.assertEqual(response.status_code, 200)

    def test_post_already_authenticated_redirects_home(self):
        """A stale code submission from an already-authenticated user redirects
        home rather than re-running the login."""
        self.client.force_login(self.user)

        url = reverse('user_signin_magic_code')
        response = self.client.post(url, {
            'email_address': self.user.email,
            'magic_code': '123456'
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_post_invalid_form(self):
        """Test POST request with invalid form data."""
        url = reverse('user_signin_magic_code')
        # Send completely empty data which should make the form invalid
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, 400)

    def test_post_nonexistent_user(self):
        """Test POST request with nonexistent user email."""
        url = reverse('user_signin_magic_code')
        response = self.client.post(url, {
            'email_address': 'nonexistent@example.com',
            'magic_code': '123456'
        })

        self.assertEqual(response.status_code, 400)

    @patch.object(MagicCodeGenerator, 'check_magic_code')
    def test_post_invalid_magic_code(self, mock_check_code):
        """Test POST request with invalid magic code."""
        # Mock invalid magic code
        mock_check_code.return_value = MagicCodeStatus.INVALID

        url = reverse('user_signin_magic_code')
        response = self.client.post(url, {
            'email_address': self.user.email,
            'magic_code': '123456'
        })

        self.assertEqual(response.status_code, 400)

    @patch.object(MagicCodeGenerator, 'check_magic_code')
    def test_post_expired_magic_code(self, mock_check_code):
        """Test POST request with expired magic code."""
        # Mock expired magic code
        mock_check_code.return_value = MagicCodeStatus.EXPIRED

        url = reverse('user_signin_magic_code')
        response = self.client.post(url, {
            'email_address': self.user.email,
            'magic_code': '123456'
        })

        self.assertEqual(response.status_code, 400)

    @patch.object(MagicCodeGenerator, 'expire_magic_code')
    @patch.object(SigninManager, 'do_login')
    @patch.object(MagicCodeGenerator, 'check_magic_code')
    @patch('user.forms.SigninMagicCodeForm')
    def test_post_valid_magic_code(self, mock_form_class, mock_check_code, mock_do_login, mock_expire_code):
        """Test POST request with valid magic code."""
        # Mock valid form
        mock_form = Mock()
        mock_form.is_valid.return_value = True
        mock_form.cleaned_data = {
            'email_address': self.user.email,
            'magic_code': '123456'
        }
        mock_form_class.return_value = mock_form

        # Mock valid magic code
        mock_check_code.return_value = MagicCodeStatus.VALID

        url = reverse('user_signin_magic_code')
        response = self.client.post(url, {
            'email_address': self.user.email,
            'magic_code': '123456'
        })

        self.assertEqual(response.status_code, 302)
        expected_url = reverse('home')
        self.assertEqual(response.url, expected_url)

        # Should perform login and expire code
        mock_do_login.assert_called_once()
        mock_expire_code.assert_called_once()


class TestSigninMagicLinkView(SyncViewTestCase):
    """
    Tests for SigninMagicLinkView - demonstrates magic link authentication testing.
    This view handles magic link clicks from emails.
    """

    def setUp(self):
        super().setUp()
        # Use the user from parent setUp()

    def test_get_missing_token(self):
        """Test GET request with missing token."""
        from django.urls.exceptions import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('user_signin_magic_link', kwargs={
                'email': self.user.email,
                'token': ''
            })

    def test_get_missing_email(self):
        """Test GET request with missing email."""
        from django.urls.exceptions import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('user_signin_magic_link', kwargs={
                'email': '',
                'token': 'test-token'
            })

    def test_get_nonexistent_user(self):
        """Test GET request with nonexistent user email."""
        url = reverse('user_signin_magic_link', kwargs={
            'email': 'nonexistent@example.com',
            'token': 'test-token'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    @patch.object(PasswordResetTokenGenerator, 'check_token')
    def test_get_invalid_token(self, mock_check_token):
        """Test GET request with invalid token."""
        mock_check_token.return_value = False

        url = reverse('user_signin_magic_link', kwargs={
            'email': self.user.email,
            'token': 'invalid-token'
        })
        response = self.client.get(url)

        self.assertSuccessResponse(response)
        self.assertTemplateRendered(response, 'user/pages/signin_magic_bad_link.html')

    @patch.object(SigninManager, 'do_login')
    @patch.object(PasswordResetTokenGenerator, 'check_token')
    def test_get_valid_token(self, mock_check_token, mock_do_login):
        """Test GET request with valid token."""
        mock_check_token.return_value = True

        url = reverse('user_signin_magic_link', kwargs={
            'email': self.user.email,
            'token': 'valid-token'
        })
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        expected_url = reverse('home')
        self.assertEqual(response.url, expected_url)

        # Should perform login
        mock_do_login.assert_called_once()

    @patch.object(PasswordResetTokenGenerator, 'check_token')
    def test_token_validation_called_correctly(self, mock_check_token):
        """Test that token validation is called with correct parameters."""
        mock_check_token.return_value = True

        url = reverse('user_signin_magic_link', kwargs={
            'email': self.user.email,
            'token': 'test-token'
        })
        _ = self.client.get(url)

        # Should check token with user and token
        mock_check_token.assert_called_once_with(user=self.user, token='test-token')

    def test_post_not_allowed(self):
        """Test that POST requests are not allowed."""
        url = reverse('user_signin_magic_link', kwargs={
            'email': self.user.email,
            'token': 'test-token'
        })
        response = self.client.post(url)

        self.assertEqual(response.status_code, 405)


class TestUserAccountView(SyncViewTestCase):
    """Tests for the signed-in user's account page."""

    def test_get_shows_logged_in_email(self):
        """The account page renders and shows the email the user is identified by."""
        self.client.force_login(self.user)

        response = self.client.get(reverse('user_account'))

        self.assertSuccessResponse(response)
        self.assertTemplateRendered(response, 'user/pages/account.html')
        self.assertContains(response, self.user.email)


class TestUserSignoutView(SyncViewTestCase):
    """Tests for the sign-out action."""

    def test_post_signs_out_and_redirects_home(self):
        """POST clears the session and returns the user to the site root."""
        self.client.force_login(self.user)

        response = self.client.post(reverse('user_signout'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
        # Session no longer carries an authenticated user.
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_get_not_allowed(self):
        """Sign-out is POST-only; a GET must not log the user out."""
        self.client.force_login(self.user)

        response = self.client.get(reverse('user_signout'))

        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)


@override_settings(
    ABUSE_PREVENTION_ENABLED=True,
    SIGNIN_PER_IP_LIMIT=1,
    SIGNIN_PER_EMAIL_HOURLY_LIMIT=1,
    SIGNIN_PER_EMAIL_DAILY_LIMIT=5,
    SIGNIN_GLOBAL_LIMIT=1000,
)
class TestUserSigninThrottling(SyncViewTestCase):
    """Rate limiting on the sign-in POST (disabled by default in tests; enabled here)."""

    def setUp(self):
        super().setUp()
        # fakeredis is one shared instance for the run; clear the throttle counters.
        get_redis_client().flushdb()

    @patch('user.views.SendMagicLinkEmailView')
    def test_within_limits_proceeds(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        self.client.post(reverse('user_signin'), {'email': 'first@example.com'})

        mock_send.send_signin_magic_link.assert_called_once()

    @patch('user.views.SendMagicLinkEmailView')
    def test_over_per_ip_limit_creates_no_user_and_sends_nothing(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        # First request is within the per-IP limit of 1.
        self.client.post(url, {'email': 'a@example.com'})
        # Second request from the same IP (distinct email so per-email is not what
        # trips) exceeds the per-IP limit.
        response = self.client.post(url, {'email': 'b@example.com'})

        # Neutral response, no account for the throttled email, no second send.
        self.assertEqual(response.status_code, 200)
        self.assertTemplateRendered(response, 'user/pages/magic_code_signin.html')
        self.assertFalse(User.objects.filter(email='b@example.com').exists())
        mock_send.send_signin_magic_link.assert_called_once()

    @override_settings(SIGNIN_PER_IP_LIMIT=100)
    @patch('user.views.SendMagicLinkEmailView')
    def test_per_email_cap_independent_of_ip(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        # Per-IP is generous here; the per-email hourly cap of 1 is what trips.
        self.client.post(url, {'email': 'repeat@example.com'})
        response = self.client.post(url, {'email': 'repeat@example.com'})

        self.assertEqual(response.status_code, 200)
        mock_send.send_signin_magic_link.assert_called_once()

    @override_settings(SIGNIN_PER_IP_LIMIT=100, SIGNIN_PER_EMAIL_HOURLY_LIMIT=100,
                       SIGNIN_PER_EMAIL_DAILY_LIMIT=1)
    @patch('user.views.SendMagicLinkEmailView')
    def test_per_email_daily_cap(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        # Only the per-email DAILY cap (1) is low enough to trip.
        self.client.post(url, {'email': 'repeat@example.com'})
        response = self.client.post(url, {'email': 'repeat@example.com'})

        self.assertEqual(response.status_code, 200)
        mock_send.send_signin_magic_link.assert_called_once()

    @override_settings(SIGNIN_PER_IP_LIMIT=100, SIGNIN_PER_EMAIL_HOURLY_LIMIT=100,
                       SIGNIN_PER_EMAIL_DAILY_LIMIT=100, SIGNIN_GLOBAL_LIMIT=1)
    @patch('user.views.SendMagicLinkEmailView')
    def test_global_ceiling_throttles_across_ips_and_emails(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        # Distinct IPs and emails, so only the global email ceiling (1) can trip.
        self.client.post(url, {'email': 'a@example.com'}, HTTP_X_FORWARDED_FOR='1.1.1.1')
        response = self.client.post(url, {'email': 'b@example.com'}, HTTP_X_FORWARDED_FOR='2.2.2.2')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='b@example.com').exists())
        mock_send.send_signin_magic_link.assert_called_once()

    @override_settings(ABUSE_PREVENTION_ENABLED=False)
    @patch('user.views.SendMagicLinkEmailView')
    def test_disabled_flag_does_not_throttle(self, mock_send_view_class):
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        for email in ('x@example.com', 'y@example.com', 'z@example.com'):
            self.client.post(url, {'email': email})

        self.assertEqual(mock_send.send_signin_magic_link.call_count, 3)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST='smtp.example.com', EMAIL_PORT=587, EMAIL_HOST_USER='u',
        DEFAULT_FROM_EMAIL='from@example.com', SERVER_EMAIL='srv@example.com',
    )
    @patch('user.views.SendMagicLinkEmailView')
    def test_throttle_sends_one_coalesced_admin_alert(self, mock_send_view_class):
        from django.core import mail
        mock_send = mock_send_view_class.return_value
        mock_send.send_signin_magic_link.return_value = HttpResponse('ok')

        url = reverse('user_signin')
        self.client.post(url, {'email': 'a@example.com'})  # within per-IP limit of 1
        self.client.post(url, {'email': 'b@example.com'})  # over -> alert
        self.client.post(url, {'email': 'c@example.com'})  # over -> coalesced, no 2nd alert

        admin_alerts = [m for m in mail.outbox if 'abuse alert' in m.subject]
        self.assertEqual(len(admin_alerts), 1)


@override_settings(ABUSE_PREVENTION_ENABLED=True)
class TestSigninVerifyCooldown(SyncViewTestCase):
    """Cooldown-backoff and hard cap on magic-code verification."""

    def setUp(self):
        super().setUp()
        get_redis_client().flushdb()
        # Prime a known valid magic code into the client session.
        session = self.client.session
        session[MagicCodeGenerator.MAGIC_CODE] = 'abcdef'
        session[MagicCodeGenerator.MAGIC_CODE_TIMESTAMP] = MagicCodeGenerator.get_elapsed_seconds()
        session.save()
        self.url = reverse('user_signin_magic_code')

    def _post_code(self, code):
        return self.client.post(self.url, {'email_address': self.user.email, 'magic_code': code})

    @override_settings(
        SIGNIN_VERIFY_FREE_ATTEMPTS=0,
        SIGNIN_VERIFY_FIRST_DELAY_SECS=5,
        SIGNIN_VERIFY_MAX_DELAY_SECS=10,
        SIGNIN_VERIFY_MAX_FAILURES=99,
    )
    def test_immediate_retry_is_blocked_by_cooldown(self):
        # First wrong attempt registers a cooldown (0 free attempts).
        self.assertEqual(self._post_code('wrongg').status_code, 400)
        # The immediate second attempt is rejected fast by the cooldown (429),
        # without the code even being checked.
        self.assertEqual(self._post_code('wrongg').status_code, 429)

    @override_settings(
        SIGNIN_VERIFY_FREE_ATTEMPTS=0,
        SIGNIN_VERIFY_FIRST_DELAY_SECS=0,
        SIGNIN_VERIFY_MAX_FAILURES=2,
    )
    def test_hard_cap_invalidates_the_code(self):
        # No cooldown (delay 0); two wrong guesses reach the cap and invalidate.
        self._post_code('wrongg')
        self.assertEqual(self._post_code('wrongg').status_code, 400)
        # The real code no longer works -- it was invalidated at the cap.
        self.assertEqual(self._post_code('abcdef').status_code, 400)

    @override_settings(
        SIGNIN_VERIFY_FREE_ATTEMPTS=0,
        SIGNIN_VERIFY_FIRST_DELAY_SECS=0,
        SIGNIN_VERIFY_MAX_FAILURES=99,
    )
    def test_correct_code_logs_in_and_resets_state(self):
        self._post_code('wrongg')  # one failure recorded
        response = self._post_code('abcdef')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
        self.assertNotIn('magic_code_failures', self.client.session)

    @override_settings(SIGNIN_VERIFY_FREE_ATTEMPTS=99, SIGNIN_VERIFY_PER_IP_LIMIT=1)
    def test_per_ip_backstop_blocks_session_cycling(self):
        # Cooldown never blocks here; the per-IP limit of 1 does.
        self._post_code('wrongg')
        self.assertEqual(self._post_code('wrongg').status_code, 429)

    @override_settings(
        SIGNIN_VERIFY_FREE_ATTEMPTS=99,
        SIGNIN_VERIFY_PER_IP_LIMIT=1,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST='smtp.example.com', EMAIL_PORT=587, EMAIL_HOST_USER='u',
        DEFAULT_FROM_EMAIL='from@example.com', SERVER_EMAIL='srv@example.com',
    )
    def test_per_ip_backstop_trip_sends_one_coalesced_alert(self):
        from django.core import mail

        self._post_code('wrongg')  # first attempt within the backstop of 1
        self._post_code('wrongg')  # second trips the backstop -> alert
        self._post_code('wrongg')  # still tripped -> coalesced, no second alert

        alerts = [m for m in mail.outbox if 'abuse alert' in m.subject]
        self.assertEqual(len(alerts), 1)
        self.assertIn('verify-per-ip', alerts[0].subject)

    def test_disabled_flag_has_no_cooldown(self):
        with override_settings(ABUSE_PREVENTION_ENABLED=False):
            # Many wrong attempts, all plain 400s -- no cooldown, no 429.
            statuses = {self._post_code('wrongg').status_code for _ in range(6)}
        self.assertEqual(statuses, {400})
