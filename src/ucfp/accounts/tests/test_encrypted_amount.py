"""The persisted entry amount is encrypted at rest, while preserving the precision
and positivity guarantees the plain DECIMAL column and its CheckConstraint gave."""
from datetime import date
from decimal import Decimal

from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings

from organization.models import Organization

from ucfp.accounts.enums import SideType
from ucfp.accounts.models import (
    AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord )

_KEY = Fernet.generate_key().decode()


@override_settings( FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY, ) )
class EncryptedAmountTest( TestCase ):

    def setUp( self ):
        organization = Organization.objects.create( name = 'Org' )
        books = BooksOfAccountRecord.objects.create( organization = organization )
        self.account = AccountRecord.objects.create( books = books, name = 'Cash' )
        self.transaction = TransactionRecord.objects.create(
            books = books, transaction_date = date( 2026, 1, 1 ) )
        return

    def _entry( self, amount ):
        return EntryRecord.objects.create(
            account = self.account, transaction = self.transaction,
            amount = amount, entry_direction = SideType.DEBIT )

    def test_amount_round_trips_with_exact_precision( self ):
        entry = self._entry( Decimal( '12345.67891' ) )
        reloaded = EntryRecord.objects.get( pk = entry.pk )
        self.assertEqual( reloaded.amount, Decimal( '12345.67891' ) )

    def test_amount_is_ciphertext_in_the_database( self ):
        entry = self._entry( Decimal( '12345.67891' ) )
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT amount FROM {EntryRecord._meta.db_table} WHERE id = %s', [ entry.pk ] )
            stored = cursor.fetchone()[ 0 ]
        self.assertNotIn( '12345', stored )   # not readable at rest

    def test_amount_is_quantized_to_scale_on_write( self ):
        entry = self._entry( Decimal( '1.123456789' ) )   # nine places
        reloaded = EntryRecord.objects.get( pk = entry.pk )
        self.assertEqual( reloaded.amount, Decimal( '1.12346' ) )   # five places, ROUND_HALF_UP

    def test_non_positive_amount_is_rejected_as_it_is_saved( self ):
        with self.assertRaises( ValidationError ):
            self._entry( Decimal( '0' ) )
