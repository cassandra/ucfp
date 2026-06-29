"""The Journal view: a `BooksOfAccount`'s entries in transaction order.

The "book of original entry" -- postings by transaction, the counterpart to `Chart` (structure)
and `Ledger` (balances). Minimal for now: one account's entries with a running balance, the form
the results-page drill-down needs. A fuller Journal (all accounts, filtering, paging) is future
work. A read-only view: it never mutates the books.
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
        debit_normal = account.account_normal_type == SideType.DEBIT
        running      = Decimal( '0' )   # credit-positive, as the Ledger's signed balance is
        entries      = []
        for transaction in sorted( self._books.transactions,
                                   key = lambda txn : txn.transaction_date ):
            for entry in transaction.entries:
                if entry.account is not account:
                    continue
                running += entry.signed_amount
                counterparts = ', '.join(
                    other.account.name for other in transaction.entries
                    if other.account is not account )
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
