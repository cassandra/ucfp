"""Model fields that encrypt their value at rest.

An encrypted field stores an opaque token in a text column and (de)serializes a
typed Python value around a cipher, so the value is unreadable in the stored
database without the key. Storage is always text -- never a native JSON or
numeric column -- because the stored form is ciphertext (a native JSON column
would reject it). An encrypted value therefore cannot be used for lookups,
ordering, or aggregation: it is only stored and read back whole.

The cipher is selected by ``settings.FIELD_ENCRYPTION_CODEC``:

- ``fernet`` (default): authenticated encryption with key rotation. The first of
  ``settings.FIELD_ENCRYPTION_KEYS`` encrypts; any of them decrypts, so a new key
  is added at the front and an old one retired once nothing uses it. Keys live in
  settings, never in the database.
- ``identity``: a pass-through that stores plaintext, for measuring the cipher's
  overhead without changing the schema (the column is text either way). Refused
  unless ``DEBUG``, so a real deployment can never store plaintext.
"""
import json
from decimal import Decimal
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

_FERNET   = 'fernet'
_IDENTITY = 'identity'


class _EncryptedField( models.TextField ):
    """Base for the encrypted fields: encrypt on the way to the database, decrypt
    on the way back. Subclasses supply the value<->bytes conversion for their type."""

    def _to_bytes( self, value ) -> bytes:
        raise NotImplementedError

    def _from_bytes( self, data : bytes ):
        raise NotImplementedError

    def get_prep_value( self, value ):
        if value is None:
            return None
        return _active_cipher().encrypt( self._to_bytes( value ) )

    def from_db_value( self, value, expression, connection ):
        if value is None:
            return None
        return self._from_bytes( _active_cipher().decrypt( value ) )

    def to_python( self, value ):
        # The database-read path goes through from_db_value; everywhere else the
        # value is already the typed object. Return it unchanged rather than let
        # TextField coerce a dict or Decimal to its string form.
        return value


class EncryptedTextField( _EncryptedField ):

    def _to_bytes( self, value ) -> bytes:
        return str( value ).encode( 'utf-8' )

    def _from_bytes( self, data : bytes ) -> str:
        return data.decode( 'utf-8' )


class EncryptedJSONField( _EncryptedField ):

    def _to_bytes( self, value ) -> bytes:
        return json.dumps( value ).encode( 'utf-8' )

    def _from_bytes( self, data : bytes ):
        return json.loads( data.decode( 'utf-8' ) )


class EncryptedDecimalField( _EncryptedField ):

    def _to_bytes( self, value ) -> bytes:
        return str( value ).encode( 'utf-8' )

    def _from_bytes( self, data : bytes ) -> Decimal:
        # str<->Decimal round-trips exactly, preserving the stored precision.
        return Decimal( data.decode( 'utf-8' ) )


# --------------------------------------------------------------------------- #
# Cipher: private to the fields above. Selected by settings and cached per
# (codec, keys) so a read/write pays only the attribute reads.

class _Cipher:
    """Turns bytes into storable text and back."""

    def encrypt( self, data : bytes ) -> str:
        raise NotImplementedError

    def decrypt( self, token : str ) -> bytes:
        raise NotImplementedError


class _FernetCipher( _Cipher ):

    def __init__( self, keys : tuple ):
        if not keys:
            raise ImproperlyConfigured(
                'FIELD_ENCRYPTION_KEYS is empty; a key is required to store encrypted fields.' )
        self._multi = MultiFernet( [ Fernet( key ) for key in keys ] )
        return

    def encrypt( self, data : bytes ) -> str:
        return self._multi.encrypt( data ).decode( 'ascii' )

    def decrypt( self, token : str ) -> bytes:
        try:
            return self._multi.decrypt( token.encode( 'ascii' ) )
        except InvalidToken as error:
            raise ValueError(
                'Could not decrypt a stored value (wrong key, or a key rotated out of use).'
            ) from error


class _IdentityCipher( _Cipher ):

    def encrypt( self, data : bytes ) -> str:
        return data.decode( 'utf-8' )

    def decrypt( self, token : str ) -> bytes:
        return token.encode( 'utf-8' )


@lru_cache( maxsize = None )
def _cipher_for( codec : str, keys : tuple ) -> _Cipher:
    if codec == _FERNET:
        return _FernetCipher( keys )
    if codec == _IDENTITY:
        return _IdentityCipher()
    raise ImproperlyConfigured( f'Unknown FIELD_ENCRYPTION_CODEC: {codec!r}.' )


def _active_cipher() -> _Cipher:
    codec = getattr( settings, 'FIELD_ENCRYPTION_CODEC', _FERNET )
    if ( codec == _IDENTITY ) and ( not settings.DEBUG ):
        raise ImproperlyConfigured(
            "The 'identity' field-encryption codec stores plaintext and is refused outside DEBUG." )
    keys = tuple( getattr( settings, 'FIELD_ENCRYPTION_KEYS', () ) )
    return _cipher_for( codec, keys )
