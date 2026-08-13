"""Model fields that encrypt their value at rest, and a document-model base built
on them.

An encrypted field stores an opaque token in a text column and (de)serializes a
typed Python value around a cipher, so the value is unreadable in the stored
database without the key. Storage is always text -- never a native JSON or
numeric column -- because the stored form is ciphertext (a native JSON column
would reject it). An encrypted value therefore cannot be used for lookups,
ordering, or aggregation: it is only stored and read back whole.

``EncryptedJsonDocumentModel`` is the counterpart to ``JsonDocumentModel``: a
record subclasses it (rather than ``JsonDocumentModel``) to store its document
encrypted, so the choice is visible on the class declaration.

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
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import DecimalValidator
from django.db import models
from django.utils.functional import cached_property

from common.models import JsonDocumentModel, build_bound_validators

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
    """A decimal field with the precision and bounds of a BoundedDecimalField, but
    stored encrypted. The database only sees ciphertext, so the guarantees a
    ``DECIMAL`` column and a CheckConstraint would give are applied here on the
    write path instead: the value is quantized to ``decimal_places``, then validated
    (digit count and bounds), so an out-of-range value is rejected as it is saved
    rather than silently stored. ``str``<->``Decimal`` round-trips exactly, so the
    quantized precision is preserved on read."""

    def __init__( self, *args,
                  max_digits     = None,
                  decimal_places = None,
                  min_value      = None,
                  max_value      = None,
                  exclusive_min  = False,
                  exclusive_max  = False,
                  **kwargs ):
        self.max_digits     = max_digits
        self.decimal_places = decimal_places
        self.min_value      = min_value
        self.max_value      = max_value
        self.exclusive_min  = exclusive_min
        self.exclusive_max  = exclusive_max
        super().__init__( *args, **kwargs )
        return

    @cached_property
    def validators( self ) -> list:
        built = list( super().validators )
        if ( self.max_digits is not None ) and ( self.decimal_places is not None ):
            built.append( DecimalValidator( self.max_digits, self.decimal_places ) )
        built.extend( build_bound_validators(
            self.min_value, self.max_value, self.exclusive_min, self.exclusive_max ) )
        return built

    def _to_bytes( self, value ) -> bytes:
        number = value if isinstance( value, Decimal ) else Decimal( str( value ) )
        if self.decimal_places is not None:
            number = number.quantize(
                Decimal( 1 ).scaleb( -self.decimal_places ), rounding = ROUND_HALF_UP )
        # Validate on the write path so a bad value raises as it is saved -- the role
        # the DECIMAL column and its CheckConstraint played before encryption.
        self.run_validators( number )
        return str( number ).encode( 'utf-8' )

    def _from_bytes( self, data : bytes ) -> Decimal:
        return Decimal( data.decode( 'utf-8' ) )

    def deconstruct( self ):
        name, path, args, kwargs = super().deconstruct()
        if self.max_digits is not None:
            kwargs[ 'max_digits' ] = self.max_digits
        if self.decimal_places is not None:
            kwargs[ 'decimal_places' ] = self.decimal_places
        if self.min_value is not None:
            kwargs[ 'min_value' ] = self.min_value
        if self.max_value is not None:
            kwargs[ 'max_value' ] = self.max_value
        if self.exclusive_min:
            kwargs[ 'exclusive_min' ] = self.exclusive_min
        if self.exclusive_max:
            kwargs[ 'exclusive_max' ] = self.exclusive_max
        return name, path, args, kwargs


class EncryptedJsonDocumentModel( JsonDocumentModel ):
    """A JsonDocumentModel whose `data` document is encrypted at rest. A record
    subclasses this in place of JsonDocumentModel to store its document encrypted."""

    data = EncryptedJSONField( default = dict )

    class Meta:
        abstract = True


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
        try:
            self._multi = MultiFernet( [ Fernet( key ) for key in keys ] )
        except ValueError as error:
            raise ImproperlyConfigured(
                'FIELD_ENCRYPTION_KEYS holds an invalid key: each must be 32 url-safe '
                'base64-encoded bytes -- 44 characters ending in "=", as produced by '
                'cryptography.fernet.Fernet.generate_key(). Check that a trailing "=" '
                'was not dropped.'
            ) from error
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
