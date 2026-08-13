"""The cookie-usage notice is shown only to an anonymous, not-yet-acknowledged visitor
when authentication is enabled, and acknowledgment persists for the session."""
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

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
