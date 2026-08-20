import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from common.redis_client import get_redis_client
from notify.models import UnsubscribedEmail
from notify.views import resubscribe_url_for
from organization.models import Organization
from user.magic_code_generator import MagicCodeGenerator
from user.signin_manager import SigninManager
from testing.view_test_base import SyncViewTestCase

logging.disable(logging.CRITICAL)

User = get_user_model()

_CODE_PAGE = 'user/pages/magic_code.html'


def _auth_user_id( client ):
    return client.session.get('_auth_user_id')


@override_settings(SUPPRESS_AUTHENTICATION=False)
class ConvertToGuestViewTest(TestCase):
    """The Anonymous -> Guest conversion, on a cloud deployment (where Anonymous visitors exist)."""

    def test_post_converts_anonymous_visitor_to_a_single_guest(self):
        response = self.client.post( reverse( 'convert_to_guest' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( 1, User.objects.count() )
        self.assertTrue( User.objects.get().is_guest )

    def test_get_does_not_convert_and_is_rejected(self):
        # POST-only, so a crawled GET can never mint an account.
        response = self.client.get( reverse( 'convert_to_guest' ) )

        self.assertEqual( 405, response.status_code )
        self.assertEqual( 0, User.objects.count() )

    def test_already_signed_in_visitor_gets_no_second_account(self):
        existing = User.objects.create_user( email = 'has@example.com' )
        self.client.force_login( existing )

        response = self.client.post( reverse( 'convert_to_guest' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( 1, User.objects.count() )


@override_settings(SUPPRESS_AUTHENTICATION=False)
class OnboardingPagesAnonymousTest(TestCase):
    """The onboarding pages a visitor with no account reaches without signing in or writing data."""

    def test_explain_and_preview_are_reachable_and_write_nothing(self):
        for name in [ 'explain', 'preview' ]:
            with self.subTest( page = name ):
                self.assertEqual( 200, self.client.get( reverse( name ) ).status_code )
        self.assertEqual( 0, User.objects.count() )
        self.assertEqual( 0, Organization.objects.count() )

    def test_marketing_home_funnels_to_explain(self):
        # The anonymous cloud visitor's site root is the marketing page, whose CTA now leads into
        # the onboarding flow (Explain) rather than straight to sign-in.
        response = self.client.get( reverse( 'home' ) )

        self.assertEqual( 200, response.status_code )
        self.assertContains( response, reverse( 'explain' ) )


@override_settings(SUPPRESS_AUTHENTICATION=False)
class CloudAuthViewTest(SyncViewTestCase):
    """Base for the sign-in / magic-code / account view tests, pinned to the cloud deployment.

    These behaviors are cloud-only: under SUPPRESS_AUTHENTICATION the self-hosted middleware logs every
    request in as the singleton Guest, so there is no sign-in (the form redirects home) and the account
    page shows the self-hosted notice instead of an email prompt. Pinning the mode here keeps the suite
    deterministic regardless of the ambient UCFP_SUPPRESS_AUTHENTICATION env var -- each test states the
    deployment it describes rather than inheriting it. Self-hosted behavior is covered separately (with
    the setting overridden True)."""


@patch.object(SigninManager, 'send_magic_email')
class TestUserSigninView(CloudAuthViewTest):
    """The returning-user sign-in form and its unknown-email 'start a Guest' branch."""

    def test_get_renders_the_signin_page(self, _mock_send):
        response = self.client.get( reverse('user_signin') )
        self.assertSuccessResponse( response )
        self.assertTemplateRendered( response, 'user/pages/signin.html' )

    def test_get_when_authenticated_redirects_home(self, _mock_send):
        self.client.force_login( self.user )
        response = self.client.get( reverse('user_signin') )
        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )

    def test_post_without_email_is_bad_request(self, _mock_send):
        self.assertEqual( 400, self.client.post( reverse('user_signin'), {} ).status_code )

    def test_post_invalid_email_is_bad_request(self, _mock_send):
        self.assertEqual( 400, self.client.post( reverse('user_signin'),
                                                 { 'email': 'not-an-email' } ).status_code )

    def test_post_verified_account_sends_a_code(self, mock_send):
        response = self.client.post( reverse('user_signin'), { 'email': self.user.email } )

        self.assertRedirects( response, reverse('magic_code'), fetch_redirect_response = False )
        mock_send.assert_called_once()
        self.assertEqual( self.user, mock_send.call_args.kwargs['user'] )
        # No new account for a known address.
        self.assertEqual( 1, User.objects.count() )

    def test_post_unknown_email_starts_a_guest_with_a_pending_claim(self, mock_send):
        response = self.client.post( reverse('user_signin'), { 'email': 'newcomer@example.com' } )

        self.assertRedirects( response, reverse('magic_code'), fetch_redirect_response = False )
        guest = User.objects.exclude( pk = self.user.pk ).get()
        self.assertTrue( guest.is_guest )
        self.assertEqual( 'newcomer@example.com', guest.pending_email )   # pending, not the verified slot
        self.assertIsNone( guest.email )
        self.assertEqual( _auth_user_id( self.client ), str( guest.pk ) )   # started + signed in
        mock_send.assert_called_once()

    def test_post_canonicalizes_the_email( self, _mock_send ):
        self.client.post( reverse('user_signin'), { 'email': 'Mixed.Case@Example.COM' } )
        guest = User.objects.exclude( pk = self.user.pk ).get()
        self.assertEqual( 'mixed.case@example.com', guest.pending_email )


# Deliberately NOT mocking send_magic_email: this exercises the real send so the unsubscribe block
# (EmailSender.send) actually fires and the view's catch is what we are testing.
class TestUserSigninUnsubscribed(CloudAuthViewTest):
    """Regression: an unsubscribed address is not dead-ended on sign-in. The unsubscribe list is the
    recipient's off-switch and is honored even for the auth email, so the magic send is blocked; the
    view must surface the re-enable page (with a resubscribe link) rather than the code page. Guards
    against the send being moved out from behind the wrapper that catches UnsubscribedEmailError."""

    def test_signin_to_an_unsubscribed_address_offers_re_enable_not_a_code( self ):
        UnsubscribedEmail.objects.create( email = self.user.email )

        response = self.client.post( reverse('user_signin'), { 'email': self.user.email } )

        self.assertEqual( 200, response.status_code )   # the re-enable page, not a 302 to the code page
        self.assertTemplateRendered( response, 'user/pages/signin_unsubscribed.html' )
        self.assertContains( response, resubscribe_url_for( self.user.email ) )   # the way back in
        self.assertEqual( 1, User.objects.count() )   # a blocked send mints no account


class TestMagicCodeView(CloudAuthViewTest):
    """Consuming a one-time code: it acts on the account the code was issued *for* (bound to the
    session), not one named by the request."""

    def _prime_code( self, target, code = 'abcdef' ):
        session = self.client.session
        session[ MagicCodeGenerator.MAGIC_CODE ] = code
        session[ MagicCodeGenerator.MAGIC_CODE_TIMESTAMP ] = MagicCodeGenerator.get_elapsed_seconds()
        session[ MagicCodeGenerator.MAGIC_CODE_TARGET ] = str( target.uuid )
        session.save()

    def test_get_renders_the_code_entry_page(self):
        # The sending views redirect here (Post/Redirect/Get), so GET must render the form and a reload
        # is idempotent -- no re-send.
        response = self.client.get( reverse('magic_code') )
        self.assertEqual( 200, response.status_code )
        self.assertTemplateRendered( response, _CODE_PAGE )

    def test_valid_code_signs_in_the_verified_target(self):
        self._prime_code( self.user )

        response = self.client.post( reverse('magic_code'), { 'magic_code': 'abcdef' } )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )
        self.assertEqual( _auth_user_id( self.client ), str( self.user.pk ) )

    def test_valid_code_confirms_a_signed_in_guests_pending_email(self):
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        self.client.force_login( guest )
        self._prime_code( guest )

        response = self.client.post( reverse('magic_code'), { 'magic_code': 'abcdef' } )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )        # lands on the dashboard, not the account page
        guest.refresh_from_db()
        self.assertEqual( 'claimed@example.com', guest.email )   # promoted -> Verified
        self.assertIsNone( guest.pending_email )

    def test_target_is_the_session_bound_account_not_a_request_field(self):
        # The account-takeover guard: a code issued for one account cannot be redirected onto
        # another by naming a different address in the request -- the target is server-side.
        victim = User.objects.create_user( email = 'victim@example.com' )
        self._prime_code( self.user )   # code issued for self.user

        response = self.client.post( reverse('magic_code'),
                                     { 'magic_code': 'abcdef', 'email_address': victim.email } )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( _auth_user_id( self.client ), str( self.user.pk ) )   # not the victim

    def test_invalid_code_is_rejected(self):
        self._prime_code( self.user )
        response = self.client.post( reverse('magic_code'), { 'magic_code': 'wrongg' } )
        self.assertEqual( 400, response.status_code )
        self.assertIsNone( _auth_user_id( self.client ) )


class TestCollisionHandoff(CloudAuthViewTest):
    """When a signed-in Guest verifies into a *different* existing account, the sign-in code hands off
    to the reconcile flow rather than silently switching -- it does not sign the target in yet."""

    def _prime_code( self, target ):
        session = self.client.session
        session[ MagicCodeGenerator.MAGIC_CODE ] = 'abcdef'
        session[ MagicCodeGenerator.MAGIC_CODE_TIMESTAMP ] = MagicCodeGenerator.get_elapsed_seconds()
        session[ MagicCodeGenerator.MAGIC_CODE_TARGET ] = str( target.uuid )
        session.save()

    def test_guest_verifying_a_different_account_is_handed_to_reconcile(self):
        guest = User.objects.create_guest()
        self.client.force_login( guest )
        self._prime_code( self.user )   # target is a different, verified account

        response = self.client.post( reverse('magic_code'), { 'magic_code': 'abcdef' } )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('signin_collision'), response.url )
        self.assertEqual( _auth_user_id( self.client ), str( guest.pk ) )   # not switched to the target


class TestPendingEmailClaimedRace(CloudAuthViewTest):
    """TOCTOU: a Guest's pending address is verified by *another* account between attach and confirm.
    Confirming the code must hand off to the reconcile flow -- the person proved they own the mailbox --
    rather than crash on the unique `email` constraint or silently discard their proof."""

    def _prime_code( self, target ):
        session = self.client.session
        session[ MagicCodeGenerator.MAGIC_CODE ] = 'abcdef'
        session[ MagicCodeGenerator.MAGIC_CODE_TIMESTAMP ] = MagicCodeGenerator.get_elapsed_seconds()
        session[ MagicCodeGenerator.MAGIC_CODE_TARGET ] = str( target.uuid )
        session.save()

    def test_confirming_a_claimed_pending_address_hands_off_to_reconcile(self):
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        self.client.force_login( guest )
        self._prime_code( guest )
        User.objects.create_user( email = 'claimed@example.com' )   # claimed in the interim

        response = self.client.post( reverse('magic_code'), { 'magic_code': 'abcdef' } )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('signin_collision'), response.url )   # graceful hand-off, not a 500
        guest.refresh_from_db()
        self.assertIsNone( guest.email )          # not promoted -- promotion would have collided
        self.assertIsNone( guest.pending_email )  # the moot claim is dropped
        self.assertEqual( _auth_user_id( self.client ), str( guest.pk ) )   # still the guest, pending reconcile


class TestMagicLinkView(CloudAuthViewTest):
    """Consuming a magic link: sign-in for a verified account works from any session; confirming a
    Guest's pending email works only in the browser that started it."""

    def _link( self, user ):
        token = PasswordResetTokenGenerator().make_token( user )
        return reverse('magic_link', kwargs = { 'user_uuid': str( user.uuid ), 'token': token })

    def test_verified_account_link_signs_in_from_any_session(self):
        response = self.client.get( self._link( self.user ) )
        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )
        self.assertEqual( _auth_user_id( self.client ), str( self.user.pk ) )

    def test_pending_link_in_the_same_session_confirms(self):
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        self.client.force_login( guest )

        response = self.client.get( self._link( guest ) )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )        # lands on the dashboard, not the account page
        guest.refresh_from_db()
        self.assertEqual( 'claimed@example.com', guest.email )

    def test_pending_link_claimed_before_confirm_hands_off_to_reconcile(self):
        # TOCTOU on the link path: the pending address was verified by another account in the interim, so
        # same-session confirmation hands off to reconcile instead of colliding on the unique constraint.
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        self.client.force_login( guest )
        User.objects.create_user( email = 'claimed@example.com' )   # claimed in the interim

        response = self.client.get( self._link( guest ) )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('signin_collision'), response.url )
        guest.refresh_from_db()
        self.assertIsNone( guest.email )
        self.assertIsNone( guest.pending_email )

    def test_pending_link_in_a_different_session_does_not_confirm(self):
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        # Client is NOT signed in as the guest (a different / anonymous session).

        response = self.client.get( self._link( guest ) )

        self.assertEqual( 200, response.status_code )
        self.assertTemplateRendered( response, 'user/pages/confirm_email_other_device.html' )
        guest.refresh_from_db()
        self.assertIsNone( guest.email )                 # not verified
        self.assertEqual( 'claimed@example.com', guest.pending_email )
        self.assertIsNone( _auth_user_id( self.client ) )   # and not logged in

    def test_bad_token_shows_the_bad_link_page(self):
        url = reverse('magic_link', kwargs = { 'user_uuid': str( self.user.uuid ), 'token': 'bad-token' })
        response = self.client.get( url )
        self.assertTemplateRendered( response, 'user/pages/signin_magic_bad_link.html' )


@patch.object(SigninManager, 'send_magic_email')
class TestAttachEmailView(CloudAuthViewTest):
    """A signed-in Guest attaching an email from their account page."""

    def test_unknown_email_becomes_a_pending_claim_and_is_sent(self, mock_send):
        guest = User.objects.create_guest()
        self.client.force_login( guest )

        response = self.client.post( reverse('attach_email'), { 'email': 'mine@example.com' } )

        self.assertRedirects( response, reverse('magic_code'), fetch_redirect_response = False )
        guest.refresh_from_db()
        self.assertEqual( 'mine@example.com', guest.pending_email )
        mock_send.assert_called_once()

    def test_email_of_a_verified_account_routes_to_confirmation(self, mock_send):
        # A taken (verified) address is not attached; instead a code is sent to *that* account so the
        # person can prove ownership, and the code page is shown (reconciliation follows on verify).
        guest = User.objects.create_guest()
        self.client.force_login( guest )

        response = self.client.post( reverse('attach_email'), { 'email': self.user.email } )

        self.assertRedirects( response, reverse('magic_code'), fetch_redirect_response = False )
        guest.refresh_from_db()
        self.assertIsNone( guest.pending_email )                     # not attached to the guest
        self.assertEqual( self.user, mock_send.call_args.kwargs['user'] )   # code sent to the existing account

    def test_a_verified_user_cannot_attach(self, mock_send):
        self.client.force_login( self.user )
        response = self.client.post( reverse('attach_email'), { 'email': 'other@example.com' } )
        self.assertRedirects( response, reverse('user_account'), fetch_redirect_response = False )
        mock_send.assert_not_called()


class TestUserAccountView(CloudAuthViewTest):
    """The account page adapts to the user's state."""

    def test_verified_user_sees_their_email(self):
        self.client.force_login( self.user )
        response = self.client.get( reverse('user_account') )
        self.assertContains( response, self.user.email )

    def test_navbar_shows_the_current_household_label(self):
        # The account page resolves the current household (ensure_organization) so the shared navbar
        # label renders here as on every other app page.
        self.client.force_login( self.user )
        response = self.client.get( reverse('user_account') )
        self.assertContains( response, 'current-household' )

    def test_guest_sees_the_add_email_prompt(self):
        self.client.force_login( User.objects.create_guest() )
        response = self.client.get( reverse('user_account') )
        self.assertContains( response, reverse('attach_email') )

    def test_guest_with_a_pending_claim_still_only_sees_add_email(self):
        # A pending, unconfirmed claim is not surfaced on the account page -- confirmation happens on
        # the code page, so the account page shows the same single add-email control.
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'mine@example.com' )
        self.client.force_login( guest )

        response = self.client.get( reverse('user_account') )

        self.assertContains( response, reverse('attach_email') )
        self.assertNotContains( response, 'mine@example.com' )   # the pending address is not shown


@override_settings(SUPPRESS_AUTHENTICATION=True)
class TestUserAccountViewSelfHosted(SyncViewTestCase):
    """Under self-hosted (SUPPRESS_AUTHENTICATION), the account page never solicits an email: the
    singleton Guest is the sole owner and there is no sign-in, so the add-email control is replaced by a
    neutral self-hosted notice."""

    def test_self_hosted_owner_is_not_asked_for_an_email(self):
        # The self-hosted middleware supplies the singleton-Guest identity on any request, so no
        # force_login is needed; the account page must show the notice, not the attach-email form.
        response = self.client.get( reverse('user_account') )

        self.assertContains( response, 'self-hosted deployment' )
        self.assertNotContains( response, reverse('attach_email') )


@override_settings(SUPPRESS_AUTHENTICATION=True)
class TestAuthEndpointsDisabledSelfHosted(SyncViewTestCase):
    """Under self-hosted (SUPPRESS_AUTHENTICATION) the sign-in / account-linking endpoints are rejected
    with an explanatory 400 -- there is no sign-in in a single-user deployment. The guard is on dispatch,
    so it fires for any method (a GET of a POST-only endpoint is a 400, not a 405) and before the view
    body runs (so e.g. attach_email never attaches)."""

    def _assert_rejected( self, response ):
        self.assertEqual( 400, response.status_code )
        self.assertContains( response, 'self-hosted', status_code = 400 )   # the explanation is shown

    def test_signin_is_rejected( self ):
        self._assert_rejected( self.client.get( reverse('user_signin') ) )

    def test_magic_code_is_rejected( self ):
        self._assert_rejected( self.client.get( reverse('magic_code') ) )

    def test_magic_link_is_rejected( self ):
        url = reverse('magic_link', kwargs = { 'user_uuid': str( self.user.uuid ), 'token': 'x' })
        self._assert_rejected( self.client.get( url ) )

    def test_convert_to_guest_is_rejected( self ):
        self._assert_rejected( self.client.post( reverse('convert_to_guest') ) )

    def test_attach_email_is_rejected_before_attaching( self ):
        response = self.client.post( reverse('attach_email'), { 'email': 'new@example.com' } )

        self._assert_rejected( response )
        # The dispatch guard fired before the view body, so nothing was claimed.
        self.assertFalse( User.objects.filter( pending_email = 'new@example.com' ).exists() )


class TestUserSignoutView(CloudAuthViewTest):
    """Tests for the sign-out action."""

    def test_post_signs_out_and_redirects_home(self):
        self.client.force_login( self.user )

        response = self.client.post( reverse('user_signout') )

        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )
        self.assertNotIn( '_auth_user_id', self.client.session )

    def test_get_not_allowed(self):
        self.client.force_login( self.user )
        response = self.client.get( reverse('user_signout') )
        self.assertEqual( 405, response.status_code )
        self.assertIn( '_auth_user_id', self.client.session )

    def test_a_guest_cannot_sign_out(self):
        # A Guest's session is the only handle to their data, so sign-out is Verified-only.
        guest = User.objects.create_guest()
        self.client.force_login( guest )

        response = self.client.post( reverse('user_signout') )

        self.assertEqual( 404, response.status_code )
        self.assertIn( '_auth_user_id', self.client.session )   # still signed in, data not stranded


@override_settings(
    ABUSE_PREVENTION_ENABLED=True,
    SIGNIN_PER_IP_LIMIT=1,
    SIGNIN_PER_EMAIL_HOURLY_LIMIT=1,
    SIGNIN_PER_EMAIL_DAILY_LIMIT=5,
    SIGNIN_GLOBAL_LIMIT=1000,
)
@patch.object(SigninManager, 'send_magic_email')
class TestUserSigninThrottling(CloudAuthViewTest):
    """Rate limiting on the sign-in POST (disabled by default in tests; enabled here)."""

    def setUp(self):
        super().setUp()
        get_redis_client().flushdb()   # fakeredis is shared across the run; start clean.

    # A fresh Client per post keeps each request anonymous (the unknown-email path signs a Guest in,
    # which would otherwise redirect the next post from the same session); the shared test IP still
    # trips the per-IP limit.
    def test_within_limits_proceeds(self, mock_send):
        Client().post( reverse('user_signin'), { 'email': 'first@example.com' } )
        mock_send.assert_called_once()

    def test_over_per_ip_limit_creates_no_user_and_sends_nothing(self, mock_send):
        url = reverse('user_signin')
        Client().post( url, { 'email': 'a@example.com' } )              # within the per-IP limit of 1
        response = Client().post( url, { 'email': 'b@example.com' } )   # exceeds it

        # Neutral: the same redirect to the code page as a real send, so throttling doesn't leak.
        self.assertRedirects( response, reverse('magic_code'), fetch_redirect_response = False )
        self.assertFalse( User.objects.filter( pending_email = 'b@example.com' ).exists() )
        mock_send.assert_called_once()

    @override_settings(SIGNIN_PER_IP_LIMIT=100)
    def test_per_email_cap_independent_of_ip(self, mock_send):
        url = reverse('user_signin')
        Client().post( url, { 'email': 'repeat@example.com' } )
        Client().post( url, { 'email': 'repeat@example.com' } )
        mock_send.assert_called_once()

    @override_settings(ABUSE_PREVENTION_ENABLED=False)
    def test_disabled_flag_does_not_throttle(self, mock_send):
        url = reverse('user_signin')
        for email in ('x@example.com', 'y@example.com', 'z@example.com'):
            Client().post( url, { 'email': email } )
        self.assertEqual( 3, mock_send.call_count )


@override_settings(ABUSE_PREVENTION_ENABLED=True)
class TestVerifyCooldown(CloudAuthViewTest):
    """Cooldown-backoff and hard cap on magic-code verification (target primed to a verified user)."""

    def setUp(self):
        super().setUp()
        get_redis_client().flushdb()
        session = self.client.session
        session[ MagicCodeGenerator.MAGIC_CODE ] = 'abcdef'
        session[ MagicCodeGenerator.MAGIC_CODE_TIMESTAMP ] = MagicCodeGenerator.get_elapsed_seconds()
        session[ MagicCodeGenerator.MAGIC_CODE_TARGET ] = str( self.user.uuid )
        session.save()
        self.url = reverse('magic_code')

    def _post_code(self, code):
        return self.client.post( self.url, { 'magic_code': code } )

    @override_settings(SIGNIN_VERIFY_FREE_ATTEMPTS=0, SIGNIN_VERIFY_FIRST_DELAY_SECS=5,
                       SIGNIN_VERIFY_MAX_DELAY_SECS=10, SIGNIN_VERIFY_MAX_FAILURES=99)
    def test_immediate_retry_is_blocked_by_cooldown(self):
        self.assertEqual( 400, self._post_code('wrongg').status_code )
        self.assertEqual( 429, self._post_code('wrongg').status_code )

    @override_settings(SIGNIN_VERIFY_FREE_ATTEMPTS=0, SIGNIN_VERIFY_FIRST_DELAY_SECS=0,
                       SIGNIN_VERIFY_MAX_FAILURES=2)
    def test_hard_cap_invalidates_the_code(self):
        self._post_code('wrongg')
        self.assertEqual( 400, self._post_code('wrongg').status_code )
        self.assertEqual( 400, self._post_code('abcdef').status_code )   # real code now invalidated

    @override_settings(SIGNIN_VERIFY_FREE_ATTEMPTS=0, SIGNIN_VERIFY_FIRST_DELAY_SECS=0,
                       SIGNIN_VERIFY_MAX_FAILURES=99)
    def test_correct_code_logs_in_and_resets_state(self):
        self._post_code('wrongg')
        response = self._post_code('abcdef')
        self.assertEqual( 302, response.status_code )
        self.assertEqual( reverse('home'), response.url )
        self.assertNotIn( 'magic_code_failures', self.client.session )

    @override_settings(SIGNIN_VERIFY_FREE_ATTEMPTS=99, SIGNIN_VERIFY_PER_IP_LIMIT=1)
    def test_per_ip_backstop_blocks_session_cycling(self):
        self._post_code('wrongg')
        self.assertEqual( 429, self._post_code('wrongg').status_code )

    def test_disabled_flag_has_no_cooldown(self):
        with override_settings(ABUSE_PREVENTION_ENABLED=False):
            statuses = { self._post_code('wrongg').status_code for _ in range(6) }
        self.assertEqual( { 400 }, statuses )
