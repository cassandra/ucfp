"""The persistence boundary: maps the `BooksOfAccount` domain to/from its `*Record` rows.

This is the *only* module that imports both the domain (`books.py`) and the Django
records (`models.py`); the domain stays persistence-ignorant and the records stay
behavior-free. `save` writes a whole books graph for an organization; `load` rebuilds the
domain graph from a stored books. Identity within a run is by object/row, so the mapping
keeps its own domain<->record correspondence rather than relying on any shared key.
"""
from django.db import transaction

from .books import Account, BooksOfAccount, Entry, Transaction
from .models import AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord
from .schemas import Handle
from organization.models import Organization


def _handle_string( handle : Handle ) -> str:
    """A handle's persisted string form (its identity, per the Handle contract), or None. The
    reloaded account carries this string back as its handle -- a str satisfies the protocol --
    so identity round-trips without the planner's original handle type."""
    if handle is None:
        return None
    return str( handle )


class BooksOfAccountRepository:
    """Persists and reloads `BooksOfAccount` aggregates."""

    @transaction.atomic
    def save( self, books : BooksOfAccount, organization : Organization ) -> BooksOfAccountRecord:
        """Persist `books` for `organization` as a new record graph, returning the root.

        Accounts are written parents-first (the domain builds them in that order), so each
        child's parent record exists when it is referenced; transactions and their entries
        follow, mapping each domain account to the record just created for it."""
        books_record = BooksOfAccountRecord.objects.create(
            organization = organization, label = books.label )
        record_by_account = dict()
        for account in books.accounts:
            parent_record = record_by_account[ account.parent ] if account.parent is not None else None
            record_by_account[ account ] = AccountRecord.objects.create(
                books             = books_record,
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
            )
            continue
        for txn in books.transactions:
            txn_record = TransactionRecord.objects.create(
                books            = books_record,
                uuid             = txn.transaction_uuid,
                transaction_date = txn.transaction_date,
                description      = txn.description,
            )
            for entry in txn.entries:
                EntryRecord.objects.create(
                    transaction     = txn_record,
                    account         = record_by_account[ entry.account ],
                    amount          = entry.amount,
                    entry_direction = entry.entry_direction,
                    description     = entry.description,
                )
                continue
            continue
        return books_record

    def load( self, books_record : BooksOfAccountRecord ) -> BooksOfAccount:
        """Rebuild the domain `BooksOfAccount` from a stored record graph."""
        records_by_id = { record.id : record for record in books_record.accounts.all() }
        account_by_id = dict()
        for record in records_by_id.values():
            self._build_account( record, records_by_id, account_by_id )
            continue
        transactions = list()
        for txn_record in books_record.transactions.all():
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
        )
        return account_by_id[ record.id ]
