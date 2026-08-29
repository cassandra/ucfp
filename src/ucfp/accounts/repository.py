"""The persistence boundary: maps the `BooksOfAccount` domain to/from its `*Record` rows.

This is the *only* module that imports both the domain (`books.py`) and the Django
records (`models.py`); the domain stays persistence-ignorant and the records stay
behavior-free. `save` writes a whole books graph for an organization; `load` rebuilds the
domain graph from a stored books. Identity within a run is by object/row, so the mapping
keeps its own domain<->record correspondence rather than relying on any shared key.
"""
from typing import Optional

from django.db import transaction

from .books import (
    Account, AccountDisplayGroup, AccountDisplayPlacement, BooksOfAccount, Entry, Transaction )
from .models import AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord
from .schemas import Handle
from organization.models import Organization


def _handle_string( handle : Optional[ Handle ] ) -> Optional[ str ]:
    """A handle's persisted string form (its identity, per the Handle contract), or None. The
    reloaded account carries this string back as its handle -- a str satisfies the protocol --
    so identity round-trips without the planner's original handle type."""
    if handle is None:
        return None
    return str( handle )


def _placement_json( placement : Optional[ AccountDisplayPlacement ] ) -> Optional[ dict ]:
    """An account's display placement as plain JSON, or None. Opaque presentation data, stored so the
    grouping computed once at capture survives a reload."""
    if placement is None:
        return None
    return { 'path'  : [ { 'key' : group.key, 'label' : group.label, 'order' : group.order }
                         for group in placement.path ],
             'order' : placement.order }


def _placement_from_json( data : Optional[ dict ] ) -> Optional[ AccountDisplayPlacement ]:
    """Rebuild a display placement from its stored JSON, or None when absent."""
    if not data:
        return None
    return AccountDisplayPlacement(
        path  = tuple( AccountDisplayGroup( key = group[ 'key' ], label = group[ 'label' ],
                                            order = group[ 'order' ] )
                       for group in data.get( 'path', () ) ),
        order = data.get( 'order', 0 ) )


class BooksOfAccountRepository:
    """Persists and reloads `BooksOfAccount` aggregates."""

    @transaction.atomic
    def save( self, books : BooksOfAccount, organization : Organization ) -> BooksOfAccountRecord:
        """Persist `books` for `organization` as a new record graph, returning the root.

        Accounts are written parents-first (the domain builds them in that order), so each child's
        parent record exists when it is referenced; the journal -- transactions and their entries --
        follows, mapping each domain account to the record just created for it."""
        books.assert_unique_handles()
        books_record      = BooksOfAccountRecord.objects.create(
            organization = organization, label = books.label )
        record_by_account = self._save_accounts( books, books_record )
        self._save_journal( books, books_record, record_by_account )
        return books_record

    def _save_accounts( self, books : BooksOfAccount,
                        books_record : BooksOfAccountRecord ) -> dict:
        """Persist the accounts parents-first and return the domain-account -> record map. Left as
        individual inserts: an account carries a self-FK to its parent (so a bulk insert would need the
        rows ordered into parentless-first layers), and a run has only a hundred-odd accounts, so the
        row-at-a-time cost here is negligible -- unlike the journal below."""
        record_by_account = dict()
        for account in books.accounts:
            parent_record = record_by_account[ account.parent ] if account.parent is not None else None
            record_by_account[ account ] = AccountRecord.objects.create(
                books             = books_record,
                uuid              = account.account_uuid,
                parent            = parent_record,
                account_type      = account.account_type,
                system_role       = account.system_role,
                asset_class       = account.asset_class,
                is_valuation      = account.is_valuation,
                income_tax_class  = account.income_tax_class,
                expense_tax_class = account.expense_tax_class,
                name              = account.name,
                handle            = _handle_string( account.handle ),
                owner_handle      = _handle_string( account.owner_handle ),
                description       = account.description,
                closed            = account.closed,
                display_placement = _placement_json( account.display_placement ),
            )
            continue
        return record_by_account

    def _save_journal( self, books : BooksOfAccount, books_record : BooksOfAccountRecord,
                       record_by_account : dict ) -> None:
        """Persist the transactions and their entries in two bulk inserts, rather than a row per
        transaction and a row per entry. A run's journal is thousands of rows, so the row-at-a-time
        pattern was the dominant cost of capturing a run; `bulk_create` collapses it to a handful of
        statements. Between the two inserts the transactions' primary keys are read back by uuid, which
        is what lets each entry point at the transaction just written (see `_transaction_id_by_uuid`).

        The read-only write-guard (`organization.write_guard`) is a `pre_save` receiver, which
        `bulk_create` does not emit -- but a forbidden write is already refused at the `books_record`
        insert (the first write of this atomic save), rolling the whole capture back before it reaches
        these rows, so the guard's guarantee holds without a per-row signal here."""
        transaction_records = [
            TransactionRecord(
                books            = books_record,
                uuid             = txn.transaction_uuid,
                transaction_date = txn.transaction_date,
                description      = txn.description,
            )
            for txn in books.transactions
        ]
        TransactionRecord.objects.bulk_create( transaction_records )
        transaction_id_by_uuid = self._transaction_id_by_uuid( books_record )
        entry_records = [
            EntryRecord(
                transaction_id  = transaction_id_by_uuid[ txn.transaction_uuid ],
                account         = record_by_account[ entry.account ],
                amount          = entry.amount,
                entry_direction = entry.entry_direction,
                description     = entry.description,
            )
            for txn in books.transactions
            for entry in txn.entries
        ]
        EntryRecord.objects.bulk_create( entry_records )
        return

    def _transaction_id_by_uuid( self, books_record : BooksOfAccountRecord ) -> dict:
        """The stored primary key of each of this books' transactions, keyed by the uuid the domain
        minted, read back in one query.

        The entries cannot take their key from the in-memory records `bulk_create` just inserted:
        `bulk_create` backfills primary keys only where the backend can return rows from a bulk insert
        (PostgreSQL, MariaDB 10.5+, SQLite >= 3.35) -- plain MySQL, which the deployment runs, cannot,
        leaving those records key-less. Reading the keys back costs one constant-size query on a path
        that just saved thousands of rows, and it resolves the link through the transaction's own
        identity rather than through a key the insert may or may not have supplied."""
        return dict(
            TransactionRecord.objects.filter( books = books_record ).values_list( 'uuid', 'id' ) )

    def load( self, books_record : BooksOfAccountRecord ) -> BooksOfAccount:
        """Rebuild the domain `BooksOfAccount` from a stored record graph."""
        records_by_id = { record.id : record for record in books_record.accounts.all() }
        account_by_id = dict()
        for record in records_by_id.values():
            self._build_account( record, records_by_id, account_by_id )
            continue
        transactions = list()
        # Prefetch the entries in one bulk query rather than a query per transaction: a run's books holds
        # thousands of transactions, so the naive per-transaction fetch is an N+1 that dominates the
        # display-path reload. `entry_record.account_id` is the stored FK column, needing no further query.
        for txn_record in books_record.transactions.prefetch_related( 'entries' ):
            entries = [
                Entry(
                    account         = account_by_id[ entry_record.account_id ],
                    amount          = entry_record.amount,
                    entry_direction = entry_record.entry_direction,
                    description     = entry_record.description,
                )
                for entry_record in txn_record.entries.all()
            ]
            transactions.append(
                Transaction(
                    transaction_date = txn_record.transaction_date,
                    description      = txn_record.description,
                    entries          = entries,
                    transaction_uuid = txn_record.uuid,
                )
            )
            continue
        return BooksOfAccount(
            label        = books_record.label,
            accounts     = list( account_by_id.values() ),
            transactions = transactions,
        )

    def _build_account( self, record, records_by_id, account_by_id ) -> Account:
        """Reconstruct a domain Account, building its parent first (memoized), so the
        domain's parent reference and structural validation hold. Insertion into
        `account_by_id` is therefore parents-first."""
        if record.id in account_by_id:
            return account_by_id[ record.id ]
        parent = None
        if record.parent_id is not None:
            parent = self._build_account( records_by_id[ record.parent_id ], records_by_id, account_by_id )
        account_by_id[ record.id ] = Account(
            name              = record.name,
            account_type      = record.account_type,
            parent            = parent,
            system_role       = record.system_role,
            asset_class       = record.asset_class,
            is_valuation      = record.is_valuation,
            income_tax_class  = record.income_tax_class,
            expense_tax_class = record.expense_tax_class,
            handle            = record.handle,
            owner_handle      = record.owner_handle,
            description       = record.description,
            closed            = record.closed,
            account_uuid      = record.uuid,
            display_placement = _placement_from_json( record.display_placement ),
        )
        return account_by_id[ record.id ]
