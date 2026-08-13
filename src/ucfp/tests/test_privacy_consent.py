"""The cookie-usage notice is shown only to an anonymous, not-yet-acknowledged visitor
when authentication is enabled, and acknowledgment persists for the session."""
import json
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ucfp.middleware import PrivacyBannerMiddleware
from ucfp.privacy_consent import PrivacyConsent
from ucfp.session_state import SessionState

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore


def _request( user ):
    request = RequestFactory().get( '/' )
    request.user = user
    request.session = _SessionStore()
    request.session_state = SessionState.from_session( request )
    return request


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ShouldShowTest( TestCase ):

    def test_shown_to_anonymous_visitor_who_has_not_acknowledged( self ):
        self.assertTrue( PrivacyConsent.should_show( _request( AnonymousUser() ) ) )

    def test_hidden_after_acknowledgment( self ):
        request = _request( AnonymousUser() )
        PrivacyConsent.acknowledge( request )
        self.assertFalse( PrivacyConsent.should_show( request ) )

    def test_hidden_for_an_authenticated_user( self ):
        user = get_user_model().objects.create_user( email = 'a@x.test' )
        self.assertFalse( PrivacyConsent.should_show( _request( user ) ) )


class SuppressedAuthTest( TestCase ):

    @override_settings( SUPPRESS_AUTHENTICATION = True )
    def test_hidden_under_suppressed_authentication( self ):
        # A self-hosted single-user deployment has no public visitor to notify.
        self.assertFalse( PrivacyConsent.should_show( _request( AnonymousUser() ) ) )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class AcknowledgeTest( TestCase ):

    def test_acknowledgment_persists_in_the_session( self ):
        request = _request( AnonymousUser() )
        PrivacyConsent.acknowledge( request )
        self.assertTrue( SessionState.from_session( request ).cookies_acknowledged )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class MiddlewareTest( TestCase ):

    def test_middleware_attaches_the_show_flag( self ):
        request = _request( AnonymousUser() )
        PrivacyBannerMiddleware( lambda req: None )( request )
        self.assertTrue( request.show_privacy_banner )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class PrivacyBannerViewTest( TestCase ):

    _BANNER_ID = 'privacy-consent-banner'

    def test_banner_renders_on_a_public_page_for_an_anonymous_visitor( self ):
        response = self.client.get( reverse( 'privacy' ) )
        self.assertContains( response, self._BANNER_ID )

    def test_banner_renders_on_the_home_page_for_an_anonymous_visitor( self ):
        # The home page (the marketing landing for an anonymous cloud visitor) is where
        # the notice most matters; it extends the same base template.
        self.assertContains( self.client.get( reverse( 'home' ) ), self._BANNER_ID )

    def test_accept_records_the_acknowledgment_and_dismisses_in_place( self ):
        response = self.client.post( reverse( 'privacy_accept' ) )
        self.assertEqual( response.status_code, 200 )
        # The antinode reply removes the banner by id (an empty-string replace).
        self.assertEqual( json.loads( response.content )[ 'replace' ], { self._BANNER_ID: '' } )
        # The session now carries the ack, so the banner no longer renders.
        self.assertNotContains( self.client.get( reverse( 'privacy' ) ), self._BANNER_ID )

    def test_anonymous_visitor_can_post_accept_without_a_signin_redirect( self ):
        # privacy_accept is in the auth middleware's exempt set, so the anonymous POST
        # reaches the view (200) instead of being answered with the signin page.
        response = self.client.post( reverse( 'privacy_accept' ) )
        self.assertEqual( response.status_code, 200 )

    def test_no_banner_for_an_authenticated_user( self ):
        user = get_user_model().objects.create_user( email = 'a@x.test' )
        self.client.force_login( user )
        self.assertNotContains( self.client.get( reverse( 'privacy' ) ), self._BANNER_ID )
