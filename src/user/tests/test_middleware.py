import logging
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from custom.models import CustomUser
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from organization.models import Organization
from user.middleware import AuthenticationMiddleware
from testing.base_test_case import BaseTestCase

logging.disable(logging.CRITICAL)


@override_settings(SUPPRESS_AUTHENTICATION=True)
class SelfHostedIdentityMiddlewareTest(TestCase):
    """Under SUPPRESS_AUTHENTICATION, a request is logged in as the singleton self-hosted
    Guest -- a real account owning a real organization -- rather than run anonymously."""

    def setUp(self):
        self.User = get_user_model()
        return

    def test_first_request_provisions_a_single_guest_owning_one_organization(self):
        self.client.get( reverse( 'home' ) )

        self.assertEqual( 1, self.User.objects.count() )
        guest = self.User.objects.get()
        self.assertTrue( guest.is_guest )
        self.assertEqual( 1, Organization.objects.count() )
        self.assertEqual( 1, guest.organization_members.filter( is_active = True ).count() )
        return

    def test_singleton_is_reused_across_independent_sessions(self):
        # Each fresh client is a new session, so the identity middleware runs cold both
        # times; it must find the existing singleton rather than mint a second.
        Client().get( reverse( 'home' ) )
        Client().get( reverse( 'home' ) )

        self.assertEqual( 1, self.User.objects.count() )
        self.assertEqual( 1, Organization.objects.count() )
        return


class TestAuthenticationMiddleware(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.get_response = Mock(return_value=HttpResponse('success'))
        self.middleware = AuthenticationMiddleware(self.get_response)

        self.authenticated_user = CustomUser.objects.create_user(
            email='auth@example.com',
            password='authpass'
        )

    @override_settings(SUPPRESS_AUTHENTICATION=True)
    def test_middleware_bypasses_when_suppress_authentication_enabled(self):
        """Test middleware bypasses authentication when SUPPRESS_AUTHENTICATION is True."""
        request = self.factory.get('/some-protected-path')
        request.user = AnonymousUser()

        with patch('user.middleware.resolve') as mock_resolve:
            mock_resolve.return_value = Mock(url_name='protected_view', app_name='main')

            response = self.middleware(request)

            # Should call get_response directly without authentication check
            self.get_response.assert_called_once_with(request)
            self.assertEqual(response, self.get_response.return_value)

    def test_middleware_bypasses_when_user_authenticated(self):
        """Test middleware bypasses when user is already authenticated."""
        request = self.factory.get('/some-protected-path')
        request.user = self.authenticated_user

        with patch('user.middleware.resolve') as mock_resolve:
            mock_resolve.return_value = Mock(url_name='protected_view', app_name='main')

            response = self.middleware(request)

            # Should call get_response directly without authentication check
            self.get_response.assert_called_once_with(request)
            self.assertEqual(response, self.get_response.return_value)

    def test_middleware_allows_admin_app_access(self):
        """Test middleware allows access to admin app without authentication."""
        request = self.factory.get('/admin/some-admin-path')
        request.user = AnonymousUser()

        with patch('user.middleware.resolve') as mock_resolve:
            mock_resolve.return_value = Mock(url_name='admin_view', app_name='admin')

            response = self.middleware(request)

            # Should call get_response directly for admin app
            self.get_response.assert_called_once_with(request)
            self.assertEqual(response, self.get_response.return_value)

    def test_middleware_allows_exempt_signin_urls(self):
        """Test middleware allows access to exempt signin URLs."""
        exempt_urls = [
            'user_signin',
            'magic_code',
            'magic_link'
        ]

        for url_name in exempt_urls:
            with self.subTest(url_name=url_name):
                request = self.factory.get(f'/{url_name}')
                request.user = AnonymousUser()

                with patch('user.middleware.resolve') as mock_resolve:
                    mock_resolve.return_value = Mock(url_name=url_name, app_name='user')

                    response = self.middleware(request)

                    # Should call get_response directly for exempt URLs
                    self.get_response.assert_called_once_with(request)
                    self.assertEqual(response, self.get_response.return_value)

                # Reset mock for next iteration
                self.get_response.reset_mock()

    @override_settings(SUPPRESS_AUTHENTICATION=False)
    def test_middleware_redirects_unauthenticated_non_exempt_requests(self):
        """An unauthenticated request to a protected view is redirected to the public home page."""
        request = self.factory.get('/protected-view')
        request.user = AnonymousUser()

        with patch('user.middleware.resolve') as mock_resolve:
            mock_resolve.return_value = Mock(url_name='protected_view', app_name='main')

            response = self.middleware(request)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('home'))
            self.get_response.assert_not_called()   # the protected view is never reached

    def test_critical_auth_endpoints_stay_exempt(self):
        """The login-free endpoints must remain reachable without authentication -- the sign-in flow
        (so a signed-out user can get back in) and the unsubscribe/health landings. A regression that
        drops one from the exempt set would lock it behind the redirect-to-home."""
        exempt_urls = self.middleware.EXEMPT_VIEW_URL_NAMES

        self.assertIn('user_signin', exempt_urls)
        self.assertIn('magic_code', exempt_urls)
        self.assertIn('magic_link', exempt_urls)
        self.assertIn('notify_email_unsubscribe', exempt_urls)
        self.assertIn('health', exempt_urls)
        # 'admin' is exempted separately, via the resolver app_name check.


@override_settings(SUPPRESS_AUTHENTICATION=False)
class PublicPagesAnonymousAccessTest(TestCase):
    """With authentication enabled, the login-free public content pages must be reachable by an
    anonymous visitor -- a 200, not the redirect-to-home the auth middleware gives protected views.
    This guards the EXEMPT_VIEW_URL_NAMES allowlist end to end: adding a new public page without
    registering it (or dropping an existing one) would silently bounce anonymous visitors to home,
    and a broken template would surface here as a non-200 too."""

    PUBLIC_PAGE_URL_NAMES = [
        'home',
        'about',
        'compare',
        'contact',
        'privacy',
        'terms',
        'explain',
    ]

    def test_public_pages_reachable_when_anonymous(self):
        for url_name in self.PUBLIC_PAGE_URL_NAMES:
            with self.subTest( url_name = url_name ):
                response = self.client.get( reverse( url_name ) )
                self.assertEqual(
                    200, response.status_code,
                    f"'{url_name}' should be reachable by an anonymous visitor, "
                    f"got HTTP {response.status_code}"
                )
        return
