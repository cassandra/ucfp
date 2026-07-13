"""The Journal view: a `BooksOfAccount`'s entries in transaction order.

The "book of original entry" -- postings by transaction, the counterpart to `Chart` (structure)
and `Ledger` (balances). It presents one account's entries with a running balance, the form the
results-page drill-down needs. A read-only view: it never mutates the books.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from .books import Account, BooksOfAccount
from .enums import SideType


@dataclass( frozen = True )
class JournalEntry:
    """One posting to an account as a journal row: the transaction's date and memo, the other
    accounts it moved against, this account's debit or credit, and its running natural balance."""

    date         : date
    description  : str
    counterparts : str
    debit        : Optional[ Decimal ]
    credit       : Optional[ Decimal ]
    balance      : Decimal


class Journal:
    """An entries-in-order view over a `BooksOfAccount`."""

    def __init__( self, books : BooksOfAccount ):
        self._books = books

    def account_entries( self, account : Account ) -> list[ JournalEntry ]:
        """`account`'s postings as journal rows, oldest first, each carrying the running natural
        balance through that posting."""
        return self._entries_for( ( account, ), normal = account )

    def market_value_entries(
            self, holding : Account, valuation_account : Account ) -> list[ JournalEntry ]:
        """A holding's postings folded with its valuation companion's, oldest first, so the running
        balance tracks *market value* (cost basis + accumulated appreciation) -- matching the number
        the holding's results column shows. Holding and companion are debit-normal alike, so their
        postings combine into one balance; neither is listed as a counterpart of the other."""
        return self._entries_for( ( holding, valuation_account ), normal = holding )

    def _entries_for(
            self, accounts : tuple[ Account, ... ], normal : Account ) -> list[ JournalEntry ]:
        """Journal rows for `accounts` taken together -- the shared core of the per-account and
        market-value journals. One running balance spans all of them, so folding a holding with its
        valuation companion yields market value; `normal` fixes the balance's sign (the accounts'
        common natural side). Membership is by identity: a posting counts when its account is one of
        `accounts`, and counterparts are the transaction's entries in *other* accounts."""
        debit_normal = normal.account_normal_type == SideType.DEBIT
        running      = Decimal( '0' )   # credit-positive, as the Ledger's signed balance is
        entries      = []
        for transaction in sorted( self._books.transactions,
                                   key = lambda txn : txn.transaction_date ):
            for entry in transaction.entries:
                if entry.account not in accounts:
                    continue
                running += entry.signed_amount
                counterparts = ', '.join(
                    other.account.name for other in transaction.entries
                    if other.account not in accounts )
                entries.append( JournalEntry(
                    date         = transaction.transaction_date,
                    description  = transaction.description or entry.description,
                    counterparts = counterparts,
                    debit        = entry.amount if entry.entry_direction == SideType.DEBIT else None,
                    credit       = entry.amount if entry.entry_direction == SideType.CREDIT else None,
                    balance      = -running if debit_normal else running ) )
                continue
            continue
        return entries
