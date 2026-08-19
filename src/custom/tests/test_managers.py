from django.contrib.auth import get_user_model
from django.test import TestCase


class CanonicalizeEmailTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_canonicalize_email_lowercases_strips_and_collapses_blank(self):

        test_data = [
            ( '  Mixed.Case@Example.COM  ' , 'mixed.case@example.com' ),
            ( 'plain@example.com'          , 'plain@example.com'      ),
            ( ''                           , None                     ),
            ( '   '                        , None                     ),
            ( None                         , None                     ),
        ]

        for raw, expected in test_data:
            result = self.User.objects.canonicalize_email( raw )
            self.assertEqual( expected, result )
            continue
        return


class CreateGuestTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_creates_emailless_passwordless_guest(self):
        guest = self.User.objects.create_guest()
        self.assertIsNone( guest.email )
        self.assertIsNone( guest.pending_email )
        self.assertFalse( guest.has_usable_password() )
        self.assertTrue( guest.is_guest )
        return

    def test_guests_are_distinct_accounts(self):
        first = self.User.objects.create_guest()
        second = self.User.objects.create_guest()
        self.assertNotEqual( first.pk, second.pk )
        return


class VerifiedAccountForEmailTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_returns_none_for_unknown_email(self):
        self.assertIsNone( self.User.objects.verified_account_for_email( 'nobody@example.com' ) )
        return

    def test_finds_verified_account_case_insensitively(self):
        user = self.User.objects.create_user( email = 'owner@example.com' )
        found = self.User.objects.verified_account_for_email( 'Owner@Example.COM' )
        self.assertEqual( user.pk, found.pk )
        return

    def test_ignores_a_merely_pending_claim(self):
        # A Guest holding the address only as a pending (unverified) claim does not
        # own it: the unique `email` slot is empty, so it is not a collision.
        guest = self.User.objects.create_guest()
        guest.attach_pending_email( 'claimed@example.com' )
        self.assertIsNone( self.User.objects.verified_account_for_email( 'claimed@example.com' ) )
        return

    def test_returns_none_for_blank_email(self):
        self.assertIsNone( self.User.objects.verified_account_for_email( '   ' ) )
        return


class GetOrCreateByEmailTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_creates_passwordless_account_for_unknown_email(self):
        user, created = self.User.objects.get_or_create_by_email( 'brand.new@example.com' )
        self.assertTrue( created )
        self.assertEqual( 'brand.new@example.com', user.email )
        # Passwordless sign-in: the account must have no usable password.
        self.assertFalse( user.has_usable_password() )
        return

    def test_returns_existing_account_for_known_email(self):
        first, first_created = self.User.objects.get_or_create_by_email( 'repeat@example.com' )
        second, second_created = self.User.objects.get_or_create_by_email( 'repeat@example.com' )
        self.assertTrue( first_created )
        self.assertFalse( second_created )
        self.assertEqual( first.pk, second.pk )
        return

    def test_case_variants_map_to_one_account(self):
        first, _ = self.User.objects.get_or_create_by_email( 'Person@Example.com' )
        second, second_created = self.User.objects.get_or_create_by_email( 'person@example.com' )
        self.assertFalse( second_created )
        self.assertEqual( first.pk, second.pk )
        self.assertEqual( 1, self.User.objects.filter( email = 'person@example.com' ).count() )
        return

    def test_blank_email_raises(self):
        with self.assertRaises( ValueError ):
            self.User.objects.get_or_create_by_email( '   ' )
        return
