"""The Chart view: read-only navigation of a `BooksOfAccount`'s account structure.

The "chart of accounts" view -- accounts organized as a tree, found by role, type, or
tax-class. Pure structure: no balances (that is the `Ledger` view) and no mutation
(building the chart is a `Bookkeeper` mechanism). The projection's chart *conventions* --
a single cash hub, the system equity accounts, valuation companions, accounts keyed by
tax-class -- live here, where they are valid (the books are built to honor them).
"""
from typing import Optional

from .books import Account, BooksOfAccount
from .enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SystemAccountRole,
)
from .schemas import Handle


class Chart:
    """A structure view over a `BooksOfAccount`.

    Account granularity: one account per income/expense tax-class, except where identity
    matters -- per-worker `WAGES` (the Social Security cap is per worker), per-item expenses,
    and per-loan accounts. Where several accounts share a class, callers name the account
    directly. See `ucfp/FORECAST_ENGINE.md`."""

    def __init__( self, books : BooksOfAccount ):
        self._books = books

    def accounts( self, *, account_type : Optional[ AccountType ] = None ) -> list[ Account ]:
        """All accounts, optionally filtered to one effective `account_type`."""
        if account_type is None:
            return list( self._books.accounts )
        return [
            account for account in self._books.accounts
            if account.effective_account_type == account_type
        ]

    def root( self, account_type : AccountType ) -> Optional[ Account ]:
        """The parentless, type-bearing root for `account_type`, or None."""
        for account in self._books.accounts:
            if account.is_root and ( account.account_type == account_type ):
                return account
            continue
        return None

    def system_account( self, role : SystemAccountRole ) -> Optional[ Account ]:
        """The account bearing system role `role`, or None."""
        for account in self._books.accounts:
            if account.system_role == role:
                return account
            continue
        return None

    def account( self, handle : Handle ) -> Optional[ Account ]:
        """The account bearing the planner's `handle` (its own identity), or None. Matched by
        the handle's string form, the identity contract -- the query surface for associating a
        planner artifact with its resulting account."""
        target = str( handle )
        for account in self._books.accounts:
            if ( account.handle is not None ) and ( str( account.handle ) == target ):
                return account
            continue
        return None

    def holdings( self ) -> list[ Account ]:
        """The asset holdings -- accounts carrying an asset_class (valuation companions,
        which carry none, are excluded)."""
        return [ account for account in self._books.accounts if account.asset_class is not None ]

    def valuation_of( self, holding : Account ) -> Optional[ Account ]:
        """The holding's valuation companion (its is_valuation child), or None."""
        for account in self._books.accounts:
            if ( account.parent is holding ) and account.is_valuation:
                return account
            continue
        return None

    def cash_account( self ) -> Optional[ Account ]:
        """The cash hub: the first asset account classed CASH, or None."""
        for account in self._books.accounts:
            if account.asset_class == AssetClass.CASH:
                return account
            continue
        return None

    def income_account(
            self, income_tax_class : IncomeTaxClass,
            owner_handle : Optional[ Handle ] = None ) -> Optional[ Account ]:
        """A revenue account with `income_tax_class`: the first one, or -- when `owner_handle`
        is given -- the one owned by that subject (income is per (subject, class), so the owner
        disambiguates between, say, two people's Social Security). None if none matches."""
        target_owner = None if owner_handle is None else str( owner_handle )
        for account in self._books.accounts:
            if account.income_tax_class != income_tax_class:
                continue
            if ( target_owner is not None ) and (
                    ( account.owner_handle is None ) or ( str( account.owner_handle ) != target_owner ) ):
                continue
            return account
        return None

    def expense_account( self, expense_tax_class : ExpenseTaxClass ) -> Optional[ Account ]:
        """The first expense account with `expense_tax_class`, or None."""
        for account in self._books.accounts:
            if account.expense_tax_class == expense_tax_class:
                return account
            continue
        return None
