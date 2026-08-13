"""Tests for the encrypted model fields.

These exercise the fields at their database boundary -- ``get_prep_value``
(Python value -> stored token) and ``from_db_value`` (stored token -> Python
value) -- so no table is needed. Each test supplies its own key/codec via
``override_settings``, independent of the ambient environment.
"""
from decimal import Decimal

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from common.encrypted_fields import (
    EncryptedDecimalField, EncryptedJSONField, EncryptedTextField )

_KEY   = Fernet.generate_key().decode()
_KEY_2 = Fernet.generate_key().decode()


def _round_trip( field, value ):
    stored = field.get_prep_value( value )
    return stored, field.from_db_value( stored, None, None )


@override_settings( FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY, ) )
class EncryptedFieldRoundTripTest( SimpleTestCase ):

    def test_text_round_trips_and_is_opaque_at_rest( self ):
        stored, restored = _round_trip( EncryptedTextField(), 'hello, world' )
        self.assertEqual( restored, 'hello, world' )
        self.assertNotEqual( stored, 'hello, world' )

    def test_json_round_trips_as_a_dict( self ):
        value = { 'a': 1, 'b': [ 'x', 'y' ], 'c': None }
        stored, restored = _round_trip( EncryptedJSONField(), value )
        self.assertEqual( restored, value )
        self.assertNotIn( '"a"', stored )   # the stored form is not readable JSON

    def test_decimal_round_trips_with_exact_precision( self ):
        value = Decimal( '12345678.90' )
        stored, restored = _round_trip( EncryptedDecimalField(), value )
        self.assertEqual( restored, value )
        self.assertEqual( str( restored ), '12345678.90' )

    def test_none_is_left_as_none( self ):
        self.assertIsNone( EncryptedTextField().get_prep_value( None ) )
        self.assertIsNone( EncryptedJSONField().from_db_value( None, None, None ) )

    def test_same_value_encrypts_differently_each_time( self ):
        field  = EncryptedTextField()
        first  = field.get_prep_value( 'same' )
        second = field.get_prep_value( 'same' )
        self.assertNotEqual( first, second )   # random IV per value
        self.assertEqual( field.from_db_value( first, None, None ), 'same' )
        self.assertEqual( field.from_db_value( second, None, None ), 'same' )


class FailClosedTest( SimpleTestCase ):

    @override_settings( FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = () )
    def test_fernet_without_a_key_is_refused( self ):
        with self.assertRaises( ImproperlyConfigured ):
            EncryptedTextField().get_prep_value( 'x' )

    @override_settings( DEBUG = False, FIELD_ENCRYPTION_CODEC = 'identity' )
    def test_identity_codec_is_refused_outside_debug( self ):
        with self.assertRaises( ImproperlyConfigured ):
            EncryptedTextField().get_prep_value( 'x' )


@override_settings( DEBUG = True, FIELD_ENCRYPTION_CODEC = 'identity' )
class IdentityCodecTest( SimpleTestCase ):

    def test_identity_stores_plaintext_and_round_trips( self ):
        stored, restored = _round_trip( EncryptedTextField(), 'plain' )
        self.assertEqual( stored, 'plain' )   # the no-op codec stores plaintext
        self.assertEqual( restored, 'plain' )


class KeyRotationTest( SimpleTestCase ):

    def test_a_value_survives_a_key_rotation( self ):
        with override_settings(
                FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY, ) ):
            stored = EncryptedTextField().get_prep_value( 'rotate me' )
        # New key added at the front, old key retained: the old value still decrypts.
        with override_settings(
                FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY_2, _KEY ) ):
            restored = EncryptedTextField().from_db_value( stored, None, None )
        self.assertEqual( restored, 'rotate me' )

    def test_a_value_does_not_decrypt_under_an_unrelated_key( self ):
        # The ciphertext is useless without the key it was written under -- not merely
        # that it round-trips with the same key. This exercises Fernet's authentication.
        with override_settings(
                FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY, ) ):
            stored = EncryptedTextField().get_prep_value( 'secret' )
        with override_settings(
                FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY_2, ) ):
            with self.assertRaises( ValueError ):
                EncryptedTextField().from_db_value( stored, None, None )
