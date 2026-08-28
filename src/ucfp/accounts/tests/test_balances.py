"""Tests for the currency-conversion boundary helper and the persistence round-trip.

The double-entry arithmetic and invariants are the domain's, tested without a database in
`test_books.py`. What needs the database is the Repository, so it is tested here: a domain
`BooksOfAccount` saved and reloaded must come back structurally and numerically intact.
The `CurrencyConverter` (kept for the future import boundary) is pure and tested alongside.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from organization.models import Organization
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    CurrencyType,
    SystemAccountRole,
)
from ucfp.accounts.exceptions import CurrencyConversionError
from ucfp.accounts.models import AccountRecord, BooksOfAccountRecord, EntryRecord
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.accounts.schemas import CurrencyConversion, CurrencyConverter


class CurrencyConverterTests(TestCase):
    """Pure conversion logic; no database. The converter is kept for the future
    import boundary, even though the in-ledger model is single-currency."""

    def test_same_currency_is_identity(self):
        converter = CurrencyConverter()
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.USD,
            to_currency_type = CurrencyType.USD,
        )
        self.assertEqual( result, Decimal( '100' ) )

    def test_direct_conversion(self):
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '1.1' ) ), ),
        )
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.EUR,
            to_currency_type = CurrencyType.USD,
        )
        self.assertEqual( result, Decimal( '110.0' ) )

    def test_reverse_conversion_uses_inverse(self):
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '2' ) ), ),
        )
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.USD,
            to_currency_type = CurrencyType.EUR,
        )
        self.assertEqual( result, Decimal( '50' ) )

    def test_missing_conversion_raises(self):
        converter = CurrencyConverter()
        with self.assertRaises( CurrencyConversionError ):
            converter.convert(
                amount = Decimal( '100' ),
                from_currency_type = CurrencyType.EUR,
                to_currency_type = CurrencyType.USD,
            )

    def test_non_positive_rate_rejected(self):
        with self.assertRaises( ValueError ):
            CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '0' ) )

    def test_same_currency_must_have_unit_rate(self):
        with self.assertRaises( ValueError ):
            CurrencyConversion( CurrencyType.USD, CurrencyType.USD, Decimal( '2' ) )


class BooksOfAccountRepositoryTests(TestCase):
    """The domain <-> persistence round-trip: a saved books reloads intact."""

    def _build_books( self ) -> Bookkeeper:
        bookkeeper = Bookkeeper( BooksOfAccount( label = 'Plan A' ) )
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        cash = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
        stocks = bookkeeper.create_holding( asset_root, 'Brokerage', AssetClass.STOCKS )
        stocks.handle = 'brokerage-1'
        stocks.owner_handle = 'subject-a'
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        bookkeeper.record(
            date( 2026, 1, 1 ),
            [ ( cash, Decimal( '-100000' ) ), ( stocks, Decimal( '-400000' ) ),
              ( opening, Decimal( '500000' ) ) ],
            description = 'Opening balances',
        )
        return bookkeeper

    def test_save_persists_the_whole_graph(self):
        bookkeeper = self._build_books()
        organization = Organization.objects.create( name = 'Round Trip' )
        books_record = BooksOfAccountRepository().save( bookkeeper.books, organization )
        self.assertEqual( BooksOfAccountRecord.objects.count(), 1 )
        self.assertEqual(
            AccountRecord.objects.filter( books = books_record ).count(),
            len( bookkeeper.books.accounts ),
        )
        self.assertEqual( EntryRecord.objects.count(), 3 )

    def test_load_restores_balances_and_structure(self):
        bookkeeper = self._build_books()
        original_net_worth = bookkeeper.ledger.net_worth()
        organization = Organization.objects.create( name = 'Round Trip' )
        repository = BooksOfAccountRepository()

        books_record = repository.save( bookkeeper.books, organization )
        loaded = repository.load( books_record )

        reader = Bookkeeper( loaded )
        self.assertEqual( loaded.label, 'Plan A' )
        self.assertEqual( reader.ledger.net_worth(), original_net_worth )
        self.assertEqual( len( loaded.accounts ), len( bookkeeper.books.accounts ) )
        loaded_stocks = next( a for a in reader.chart.holdings() if a.name == 'Brokerage' )
        self.assertIsNotNone( reader.chart.valuation_of( loaded_stocks ) )
        # handles round-trip as their string form (a str satisfies the Handle protocol)
        self.assertEqual( loaded_stocks.handle, 'brokerage-1' )
        self.assertEqual( loaded_stocks.owner_handle, 'subject-a' )
        loaded_cash = next( a for a in reader.chart.holdings() if a.name == 'Cash' )
        self.assertIsNone( loaded_cash.handle )
        # the transaction's memo and its uuid identity round-trip (the uuid is the persisted key)
        original_txn = bookkeeper.books.transactions[ 0 ]
        loaded_txn = loaded.transactions[ 0 ]
        self.assertEqual( loaded_txn.description, 'Opening balances' )
        self.assertEqual( loaded_txn.transaction_uuid, original_txn.transaction_uuid )
        reader.assert_balanced()

    def _save_books_with_transactions( self, repository, *, transactions : int ):
        """A saved books whose journal holds `transactions` balanced postings -- the fixture for the
        query-count guard, letting one shape be reloaded at two sizes."""
        bookkeeper = Bookkeeper( BooksOfAccount( label = 'Journal' ) )
        bookkeeper.build_standard_chart()
        chart   = bookkeeper.chart
        cash    = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        for index in range( transactions ):
            bookkeeper.record(
                date( 2026, 1, 1 ),
                [ ( cash, Decimal( '-1000' ) ), ( opening, Decimal( '1000' ) ) ],
                description = f'Deposit {index}',
            )
            continue
        organization = Organization.objects.create( name = f'Journal {transactions}' )
        return repository.save( bookkeeper.books, organization )

    def test_load_query_count_does_not_scale_with_transactions(self):
        """The reload issues a fixed, small number of queries however many transactions the books holds
        -- the regression guard on the N+1 (one entries query per transaction) that dominated the
        run-display reload before the entries were prefetched."""
        repository = BooksOfAccountRepository()
        small = self._save_books_with_transactions( repository, transactions = 2 )
        large = self._save_books_with_transactions( repository, transactions = 20 )
        with CaptureQueriesContext( connection ) as small_queries:
            repository.load( small )
        with CaptureQueriesContext( connection ) as large_queries:
            repository.load( large )
        # Constant across a 10x transaction count -- the reload no longer issues a query per transaction.
        self.assertEqual( len( large_queries ), len( small_queries ) )
        # Accounts, transactions, and the single prefetched entries query: a small fixed bound.
        self.assertLessEqual( len( small_queries ), 4 )

    def test_save_query_count_does_not_scale_with_transactions(self):
        """Capturing a run writes the journal in a few bulk inserts, not a row per transaction and a row
        per entry -- the regression guard on the write-side N+1 that dominated a forecast run's persist.
        Accounts stay per-row (a self-FK, and few of them); only the journal is bulk, so a 20x journal
        must not mean 20x the writes."""
        repository = BooksOfAccountRepository()
        with CaptureQueriesContext( connection ) as small_queries:
            self._save_books_with_transactions( repository, transactions = 2 )
        with CaptureQueriesContext( connection ) as large_queries:
            self._save_books_with_transactions( repository, transactions = 40 )
        # The journal's two bulk inserts do not grow with row count at these sizes, so 20x the
        # transactions adds no per-row writes -- the counts stay effectively flat.
        self.assertLessEqual( len( large_queries ) - len( small_queries ), 2 )
        # Well under the row-at-a-time count (~130 writes for the 40-transaction books).
        self.assertLessEqual( len( large_queries ), 30 )
