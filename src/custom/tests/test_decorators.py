from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

from custom.decorators import require_verified_user

User = get_user_model()


class RequireVerifiedUserTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

        @require_verified_user
        def view( request ):
            return HttpResponse( 'ok' )

        self.view = view
        return

    def _request_as( self, user ):
        request = self.factory.get( '/gated' )
        request.user = user
        return request

    def test_verified_user_is_allowed_through(self):
        verified = User.objects.create_user( email = 'v@example.com' )
        response = self.view( self._request_as( verified ) )
        self.assertEqual( 200, response.status_code )

    def test_guest_is_rejected(self):
        guest = User.objects.create_guest()
        with self.assertRaises( Http404 ):
            self.view( self._request_as( guest ) )

    def test_guest_with_a_pending_email_is_still_rejected(self):
        guest = User.objects.create_guest()
        guest.attach_pending_email( 'pending@example.com' )   # confirming, but not yet Verified
        with self.assertRaises( Http404 ):
            self.view( self._request_as( guest ) )

    def test_anonymous_request_is_rejected(self):
        with self.assertRaises( Http404 ):
            self.view( self._request_as( AnonymousUser() ) )
