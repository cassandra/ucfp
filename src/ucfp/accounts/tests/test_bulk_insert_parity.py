"""Backend parity for the journal's bulk inserts (regression: the MySQL capture failure).

`bulk_create` only backfills the new rows' primary keys on backends whose
`can_return_rows_from_bulk_insert` is true -- PostgreSQL, MariaDB 10.5+, and SQLite 3.35+.
MySQL is *not* among them, so code that bulk-inserts parents and then references those
in-memory parents from bulk-inserted children works on the SQLite test backend and fails in
production. These tests pin the repository's journal write to backend-agnostic behavior by
running it with the returning-rows feature forced off, the way MySQL reports it.
"""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase

from organization.models import Organization
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.accounts.models import EntryRecord, TransactionRecord
from ucfp.accounts.repository import BooksOfAccountRepository


@contextmanager
def without_bulk_insert_returning():
    """Run the body with the connection reporting no primary-key backfill from `bulk_create`, as
    MySQL does. `can_return_columns_from_insert` is a `cached_property`, so an instance value
    shadows it; `can_return_rows_from_bulk_insert` reads through to it."""
    features = connection.features
    original = features.__dict__.get( 'can_return_columns_from_insert', None )
    features.__dict__[ 'can_return_columns_from_insert' ] = False
    try:
        yield
    finally:
        if original is None:
            features.__dict__.pop( 'can_return_columns_from_insert', None )
        else:
            features.__dict__[ 'can_return_columns_from_insert' ] = original


class JournalBulkInsertParityTests( TestCase ):

    def _build_books( self ) -> Bookkeeper:
        bookkeeper = Bookkeeper( BooksOfAccount( label = 'Parity' ) )
        bookkeeper.build_standard_chart()
        chart   = bookkeeper.chart
        cash    = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        for index in range( 3 ):
            bookkeeper.record(
                date( 2026, 1, index + 1 ),
                [ ( cash, Decimal( '-1000' ) ), ( opening, Decimal( '1000' ) ) ],
                description = f'Deposit {index}',
            )
            continue
        return bookkeeper

    def test_feature_shim_reproduces_the_mysql_report( self ):
        """The shim itself is what the rest of this file rests on: with it in place the connection
        reports what MySQL reports, and a plain `bulk_create` leaves the primary keys unset."""
        with without_bulk_insert_returning():
            self.assertFalse( connection.features.can_return_rows_from_bulk_insert )
        self.assertTrue( connection.features.can_return_rows_from_bulk_insert )

    def test_save_links_entries_without_relying_on_backfilled_keys( self ):
        """The capture must persist a correctly-linked journal on a backend that returns no keys from
        a bulk insert -- the production failure (`bulk_create() prohibited to prevent data loss due to
        unsaved related object 'transaction'`)."""
        bookkeeper   = self._build_books()
        organization = Organization.objects.create( name = 'Parity' )
        with without_bulk_insert_returning():
            books_record = BooksOfAccountRepository().save( bookkeeper.books, organization )
        self.assertEqual( TransactionRecord.objects.filter( books = books_record ).count(), 3 )
        self.assertEqual(
            EntryRecord.objects.filter( transaction__books = books_record ).count(), 6 )

    def test_saved_entries_attach_to_their_own_transaction( self ):
        """Each entry must land under the transaction that holds it -- a uuid-keyed relink could
        pass a row count while cross-wiring the journal."""
        bookkeeper   = self._build_books()
        organization = Organization.objects.create( name = 'Parity' )
        with without_bulk_insert_returning():
            books_record = BooksOfAccountRepository().save( bookkeeper.books, organization )
        loaded = BooksOfAccountRepository().load( books_record )
        described_by_date = { txn.transaction_date : txn.description for txn in loaded.transactions }
        for index, txn in enumerate( bookkeeper.books.transactions ):
            self.assertEqual( described_by_date[ txn.transaction_date ], txn.description )
            continue
        for txn_record in TransactionRecord.objects.filter( books = books_record ):
            self.assertEqual( txn_record.entries.count(), 2 )
            continue
        self.assertEqual( Bookkeeper( loaded ).ledger.net_worth(),
                          bookkeeper.ledger.net_worth() )
