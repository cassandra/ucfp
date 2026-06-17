"""The in-memory double-entry Ledger.

`Ledger` is the computational aggregate over a partition's books -- distinct from
`Journal`, which is the *persisted* partition record. A Ledger holds the chart's
accounts and a journal's transactions and entries (saved or unsaved) in memory,
loaded once, and answers every balance / flow query in memory rather than issuing
a database aggregate per account per call. It is also the authoritative enforcer
of the double-entry invariants -- which must hold for ephemeral books that are
never persisted -- so the cross-row transaction-balance rule lives here, not in a
database constraint.

NOTE: `flush` (optional persistence) remains stubbed pending a real need.
"""
from collections import namedtuple
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from .enums import (
    AccountType,
    AssetClass,
    CurrencyType,
    IncomeTaxClass,
    SideType,
    SystemAccountRole,
)
from .exceptions import TransactionImbalanceError
from .models import Account, Entry, Journal, Transaction

from organization.models import Organization


# One account's participation in one transaction, reduced to what the queries
# need: the transaction's date and the entry's signed magnitudes (credit-positive)
# in the account currency and the transaction currency.
_Posting = namedtuple( '_Posting', ( 'date', 'signed_amount', 'signed_transaction_amount' ) )


class Ledger:
    """In-memory double-entry books over a single partition.

    Construct once (load an existing Journal's books, or start empty against an
    organization's chart), `post` balanced transactions into it, and query
    balances and flows entirely in memory. Works with unsaved model instances; an
    optional `flush` persists held objects only when a caller wants them durable.
    """

    def __init__( self, organization : Organization ):
        self._organization = organization
        self.journal = None                  # the partition posted transactions belong to
        self._accounts = { account.pk : account for account in organization.accounts.all() }
        self._transactions = list()
        self._postings_by_account = dict()   # account pk -> list[ _Posting ]

    # -- construction (load once) --------------------------------------------

    @classmethod
    def load( cls, journal : Journal ) -> 'Ledger':
        """Build a Ledger from a persisted Journal, bulk-fetching its chart,
        transactions and entries (never one query per account)."""
        ledger = cls( journal.organization )
        ledger.journal = journal
        for transaction in journal.transactions.prefetch_related( 'entries' ):
            ledger._index( transaction, transaction.entries.all() )
            ledger._transactions.append( transaction )
            continue
        return ledger

    @classmethod
    def empty( cls, organization : Organization ) -> 'Ledger':
        """Build an empty Ledger over `organization`'s chart -- no transactions
        yet -- for ephemeral books built forward (e.g. a Forecast working set)."""
        return cls( organization )

    # -- mutation (invariant-enforcing, in memory) ---------------------------

    def post( self, transaction : Transaction, entries : Iterable[ Entry ] ) -> None:
        """Validate that `entries` balance to zero in the transaction currency and
        hold them in memory. Entries are passed explicitly because an unsaved
        transaction has no usable reverse relation. Raises on imbalance."""
        entries = list( entries )
        self._assert_transaction_balanced( entries )
        self._index( transaction, entries )
        self._transactions.append( transaction )
        return

    def record( self,
                transaction_date : date,
                currency : CurrencyType,
                signed_postings : Iterable[ tuple[ Account, Decimal ] ] ) -> Transaction:
        """Build and post a balanced transaction from (account, signed_amount)
        pairs (credit-positive); each entry's direction is derived from its sign.
        Amounts are in `currency` -- single-currency (conversion not yet handled).
        Zero-amount postings are skipped."""
        transaction = Transaction(
            journal = self.journal,
            transaction_date = transaction_date,
            currency = currency,
        )
        entries = list()
        for account, signed_amount in signed_postings:
            if signed_amount == 0:
                continue
            direction = SideType.CREDIT if signed_amount > 0 else SideType.DEBIT
            magnitude = abs( signed_amount )
            entries.append(
                Entry(
                    transaction = transaction,
                    account = account,
                    amount = magnitude,
                    transaction_amount = magnitude,
                    entry_direction = direction,
                )
            )
            continue
        self.post( transaction, entries )
        return transaction

    # -- queries (pure in-memory) --------------------------------------------

    def signed_balance( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """Credit-positive balance of `account`, cumulative through `through`
        (a date; None = all held entries), in the account's currency."""
        total = Decimal( '0' )
        for posting in self._postings_by_account.get( account.pk, () ):
            if ( through is None ) or ( posting.date <= through ):
                total += posting.signed_amount
            continue
        return total

    def flows( self, account : Account, *, start : date, end : date ) -> Decimal:
        """Net credit-positive movement on `account` within [start, end] -- the
        within-a-window primitive (e.g. fiscal-year income/expense totals)."""
        total = Decimal( '0' )
        for posting in self._postings_by_account.get( account.pk, () ):
            if start <= posting.date <= end:
                total += posting.signed_amount
            continue
        return total

    def natural_balance( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """Display balance (positive in the account type's normal direction);
        the sign-flip of `signed_balance` for debit-normal accounts."""
        signed = self.signed_balance( account, through = through )
        if account.account_normal_type == SideType.DEBIT:
            return -signed
        return signed

    def balances( self,
                  *,
                  account_type : Optional[ AccountType ] = None,
                  through      : Optional[ date ] = None ) -> dict:
        """Signed balances of every account that participates in this partition,
        optionally filtered to a single (effective) `account_type`."""
        result = dict()
        for account_pk in self._postings_by_account:
            account = self._accounts[ account_pk ]
            if ( account_type is not None ) and ( self._effective_type( account ) != account_type ):
                continue
            result[ account ] = self.signed_balance( account, through = through )
            continue
        return result

    # -- chart accessors -----------------------------------------------------

    def holdings( self ) -> list[ Account ]:
        """The asset holdings -- accounts carrying an asset_class. Valuation
        companions (no asset_class) and all other accounts are excluded."""
        return [ account for account in self._accounts.values() if account.asset_class is not None ]

    def valuation_of( self, holding : Account ) -> Optional[ Account ]:
        """The holding's valuation companion (its is_valuation child), or None."""
        for account in self._accounts.values():
            if ( account.parent_id == holding.pk ) and account.is_valuation:
                return account
            continue
        return None

    def system_account( self, role : SystemAccountRole ) -> Optional[ Account ]:
        """The account bearing system role `role`, or None."""
        for account in self._accounts.values():
            if account.system_role == role:
                return account
            continue
        return None

    def market_value( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """An account's market value: its own natural balance plus its valuation
        companion's, if any (cost + accumulated appreciation)."""
        total = self.natural_balance( account, through = through )
        valuation_account = self.valuation_of( account )
        if valuation_account is not None:
            total += self.natural_balance( valuation_account, through = through )
        return total

    def cash_account( self ) -> Optional[ Account ]:
        """The cash hub: the first asset account classed CASH (multiple cash
        accounts are not yet supported), or None."""
        for account in self._accounts.values():
            if account.asset_class == AssetClass.CASH:
                return account
            continue
        return None

    def income_account( self, income_tax_class : IncomeTaxClass ) -> Optional[ Account ]:
        """The first revenue account with `income_tax_class`, or None."""
        for account in self._accounts.values():
            if account.income_tax_class == income_tax_class:
                return account
            continue
        return None

    # -- invariants ----------------------------------------------------------

    def assert_balanced( self ) -> None:
        """Assert the whole partition's signed entries sum to zero in the
        transaction currency (every balanced transaction contributes zero, so any
        residual reveals a malformed partition)."""
        residual = sum(
            ( posting.signed_transaction_amount
              for postings in self._postings_by_account.values()
              for posting in postings ),
            Decimal( '0' ),
        )
        if residual != 0:
            raise TransactionImbalanceError(
                f'Partition does not balance (residual {residual}).'
            )
        return

    # -- persistence (optional, later) ---------------------------------------

    def flush( self ) -> None:
        """Persist held unsaved accounts / transactions / entries in bulk."""
        raise NotImplementedError

    # -- internals -----------------------------------------------------------

    def _index( self, transaction : Transaction, entries : Iterable[ Entry ] ) -> None:
        date_ = transaction.transaction_date
        for entry in entries:
            posting = _Posting(
                date = date_,
                signed_amount = entry.signed_amount,
                signed_transaction_amount = entry.signed_transaction_amount,
            )
            self._postings_by_account.setdefault( entry.account_id, list() ).append( posting )
            continue
        return

    def _assert_transaction_balanced( self, entries : Iterable[ Entry ] ) -> None:
        residual = sum(
            ( entry.signed_transaction_amount for entry in entries ),
            Decimal( '0' ),
        )
        if residual != 0:
            raise TransactionImbalanceError(
                f'Transaction does not balance (residual {residual}).'
            )
        return

    def _effective_type( self, account : Account ) -> AccountType:
        """The account's type, walking parents in memory (no DB) to the
        type-bearing root."""
        current = account
        while current.account_type is None:
            current = self._accounts[ current.parent_id ]
            continue
        return current.account_type
