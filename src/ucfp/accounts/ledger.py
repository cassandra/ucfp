"""The Ledger view: per-account balances over a `BooksOfAccount`.

The "book of final entry" view -- entries organized by account, with balances. Reads a
`Bookkeeper`'s postings index and presents signed and natural balances, flows within a
window, and the projection derivations `market_value` (cost + valuation companion) and
`net_worth` (assets - liabilities). It uses a `Chart` for the structure those derivations
need. A read-only view: it never mutates the books (that is the `Bookkeeper`'s job).
"""
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from .books import Account
from .enums import AccountType, SideType

if TYPE_CHECKING:
    from .bookkeeper import Bookkeeper


class Ledger:
    """A balance view over a `Bookkeeper`'s books."""

    def __init__( self, bookkeeper : 'Bookkeeper' ):
        self._bookkeeper = bookkeeper
        self._chart = bookkeeper.chart

    def signed_balance( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """Credit-positive balance of `account`, cumulative through `through` (None = all
        held entries)."""
        total = Decimal( '0' )
        for posting in self._bookkeeper.postings( account ):
            if ( through is None ) or ( posting.date <= through ):
                total += posting.signed_amount
            continue
        return total

    def natural_balance( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """Display balance (positive in the account type's normal direction)."""
        signed = self.signed_balance( account, through = through )
        if account.account_normal_type == SideType.DEBIT:
            return -signed
        return signed

    def flows( self, account : Account, *, start : date, end : date ) -> Decimal:
        """Net credit-positive movement on `account` within [start, end] -- the
        within-a-window primitive (e.g. fiscal-year income/expense totals)."""
        total = Decimal( '0' )
        for posting in self._bookkeeper.postings( account ):
            if start <= posting.date <= end:
                total += posting.signed_amount
            continue
        return total

    def balances( self,
                  *,
                  account_type : Optional[ AccountType ] = None,
                  through      : Optional[ date ] = None ) -> dict:
        """Signed balances keyed by account, optionally filtered to one effective
        `account_type`."""
        return {
            account : self.signed_balance( account, through = through )
            for account in self._chart.accounts( account_type = account_type )
        }

    def market_value( self, holding : Account, *, through : Optional[ date ] = None ) -> Decimal:
        """A holding's market value: its cost (own natural balance) plus its valuation
        companion's accumulated appreciation, if any."""
        total = self.natural_balance( holding, through = through )
        valuation_account = self._chart.valuation_of( holding )
        if valuation_account is not None:
            total += self.natural_balance( valuation_account, through = through )
        return total

    def net_worth( self, *, through : Optional[ date ] = None ) -> Decimal:
        """Total assets minus total liabilities (in natural terms) as of `through`."""
        assets = sum(
            ( self.natural_balance( account, through = through )
              for account in self._chart.accounts( account_type = AccountType.ASSET ) ),
            Decimal( '0' ),
        )
        liabilities = sum(
            ( self.natural_balance( account, through = through )
              for account in self._chart.accounts( account_type = AccountType.LIABILITY ) ),
            Decimal( '0' ),
        )
        return assets - liabilities
