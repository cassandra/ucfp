from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from custom.user_state import UserState, is_known, user_state


class AccountStateTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_account_state_derives_from_the_verified_email_slot(self):

        guest = self.User.objects.create_guest()
        guest_confirming = self.User.objects.create_guest()
        guest_confirming.attach_pending_email( 'claimed@example.com' )
        verified = self.User.objects.create_user( email = 'verified@example.com' )

        test_data = [
            ( guest           , UserState.GUEST    , 'is_guest'    ),
            ( guest_confirming , UserState.GUEST    , 'is_guest'    ),   # a pending claim does not change the state
            ( verified        , UserState.VERIFIED , 'is_verified' ),
        ]

        for user, expected_state, predicate in test_data:
            self.assertEqual( expected_state, user.account_state )
            self.assertEqual( expected_state, user_state( user ) )
            self.assertTrue( is_known( user ) )
            self.assertTrue( getattr( user, predicate ) )
            continue
        return

    def test_anonymous_user_is_anonymous_and_not_known(self):
        anonymous = AnonymousUser()
        self.assertEqual( UserState.ANONYMOUS, user_state( anonymous ) )
        self.assertFalse( is_known( anonymous ) )
        return

    def test_attach_pending_email_canonicalizes_and_leaves_a_guest(self):
        user = self.User.objects.create_guest()
        user.attach_pending_email( '  Mixed.Case@Example.COM ' )
        user.refresh_from_db()
        self.assertEqual( 'mixed.case@example.com', user.pending_email )
        self.assertIsNone( user.email )
        self.assertTrue( user.is_guest )   # still a Guest -- a pending claim is not yet an identity
        return

    def test_verify_pending_email_promotes_into_verified_slot(self):
        user = self.User.objects.create_guest()
        user.attach_pending_email( 'claimed@example.com' )
        user.verify_pending_email()
        user.refresh_from_db()
        self.assertEqual( 'claimed@example.com', user.email )
        self.assertIsNone( user.pending_email )
        self.assertTrue( user.is_verified )
        return

    def test_verify_without_pending_email_raises(self):
        user = self.User.objects.create_guest()
        with self.assertRaises( ValueError ):
            user.verify_pending_email()
        return


class CustomUserDisplayNameTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_get_long_display_name(self):

        test_data = [
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     last_name = 'Pampling',
                                                     email = 'sample1@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling, Sampling',
              },
            { 'user': self.User.objects.create_user( last_name = 'Pampling',
                                                     email = 'sample2@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling',
              },
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     email = 'sample3@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( email = 'sample4@example.com',
                                                     password = 'top_secret' ),
              'expected': 'sample4',
              },
        ]

        for data in test_data:
            result = data['user'].long_display_name
            self.assertEqual( data['expected'], result )
            continue
        return

    def test_get_short_display_name(self):

        test_data = [
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     last_name = 'Pampling',
                                                     email = 'sample1@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( last_name = 'Pampling',
                                                     email = 'sample2@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling',
              },
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     email = 'sample3@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( email = 'sample4@example.com',
                                                     password = 'top_secret' ),
              'expected': 'sample4',
              },
        ]

        for data in test_data:
            result = data['user'].short_display_name
            self.assertEqual( data['expected'], result )
            continue
        return
