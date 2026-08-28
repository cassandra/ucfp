"""The Ledger view: per-account balances over a `BooksOfAccount`.

The "book of final entry" view -- entries organized by account, with balances. Reads a
`Bookkeeper`'s postings index and presents signed and natural balances, flows within a
window, and the projection derivations `market_value` (cost + valuation companion) and
`net_worth` (assets - liabilities). It uses a `Chart` for the structure those derivations
need. A read-only view: it never mutates the books (that is the `Bookkeeper`'s job).
"""
import bisect
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from .books import Account
from .enums import AccountClass, AccountType, SideType

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

    def natural_flow( self, account : Account, *, start : date, end : date ) -> Decimal:
        """Display-direction movement on `account` within [start, end]: `flows` cast to the
        account type's normal side, so revenue reads as positive income and expense as positive
        spending -- the per-period figure a flow column shows."""
        signed = self.flows( account, start = start, end = end )
        if account.account_normal_type == SideType.DEBIT:
            return -signed
        return signed

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

    def type_total( self, account_type : AccountType, *, through : Optional[ date ] = None ) -> Decimal:
        """Balance rollup for an account type as of `through`: the natural-balance sum over its
        accounts. Asset valuation companions are themselves asset accounts, so an asset total
        already carries unrealized appreciation -- it reads as market value, not bare cost."""
        return sum(
            ( self.natural_balance( account, through = through )
              for account in self._chart.accounts( account_type = account_type ) ),
            Decimal( '0' ),
        )

    def class_total( self, account_class : AccountClass, *, through : Optional[ date ] = None ) -> Decimal:
        """Balance rollup for an account class as of `through`. Summed by `market_value` because a
        class names only its holdings -- their valuation companions carry no class -- so each
        holding's appreciation must be folded in to match `type_total`."""
        return sum(
            ( self.market_value( account, through = through )
              for account in self._chart.accounts( account_class = account_class ) ),
            Decimal( '0' ),
        )

    def type_flow( self, account_type : AccountType, *, start : date, end : date ) -> Decimal:
        """Flow rollup for an account type within [start, end]: the natural-direction movement
        summed over its accounts -- the per-period figure for a revenue/expense type column."""
        return sum(
            ( self.natural_flow( account, start = start, end = end )
              for account in self._chart.accounts( account_type = account_type ) ),
            Decimal( '0' ),
        )

    def class_flow( self, account_class : AccountClass, *, start : date, end : date ) -> Decimal:
        """Flow rollup for an account class within [start, end]: the natural-direction movement
        summed over its accounts -- the per-period figure for an income/expense class column."""
        return sum(
            ( self.natural_flow( account, start = start, end = end )
              for account in self._chart.accounts( account_class = account_class ) ),
            Decimal( '0' ),
        )

    def net_worth( self, *, through : Optional[ date ] = None ) -> Decimal:
        """Total assets minus total liabilities as of `through` (assets at market value)."""
        return ( self.type_total( AccountType.ASSET, through = through )
                 - self.type_total( AccountType.LIABILITY, through = through ) )


class SnapshotLedger( Ledger ):
    """A `Ledger` over an **immutable** books -- a captured run's reloaded books, never posted to again.

    It answers the same queries as `Ledger`, but the first time an account is asked about it folds that
    account's postings into a sorted cumulative-balance index, so a balance `through` a date or a `flow`
    over a window becomes a binary search rather than a re-scan of the whole posting list. The display
    path reads every account across dozens of period boundaries, so the base Ledger's per-call rescan is
    O(spans x postings); this is one sort per account plus a lookup per cell. Every derived figure
    (`market_value`, `net_worth`, the type/class rollups) composes on `signed_balance`/`flows`, so
    overriding just those two carries the whole view.

    Snapshot semantics: each account's index is built once and cached on this view, reflecting the books
    **as of the first query for that account**. That is exactly right for immutable run books; it must
    not be used over a books still being posted to -- the engine keeps the live `Ledger` -- and a new
    view must be created after any change.
    """

    def __init__( self, bookkeeper : 'Bookkeeper' ):
        super().__init__( bookkeeper )
        self._cumulative_by_account : dict = dict()

    def signed_balance( self, account : Account, *, through : Optional[ date ] = None ) -> Decimal:
        dates, prefix = self._cumulative( account )
        if not dates:
            return Decimal( '0' )
        if through is None:
            return prefix[ -1 ]
        return self._prefix_through( dates, prefix, through, inclusive = True )

    def flows( self, account : Account, *, start : date, end : date ) -> Decimal:
        dates, prefix = self._cumulative( account )
        if not dates:
            return Decimal( '0' )
        # Inclusive [start, end]: the balance through end less the balance strictly before start -- so a
        # posting dated exactly `start` counts, matching the base Ledger's `start <= date <= end`.
        return ( self._prefix_through( dates, prefix, end, inclusive = True )
                 - self._prefix_through( dates, prefix, start, inclusive = False ) )

    def _cumulative( self, account : Account ) -> tuple:
        """This account's `(dates, prefix)` index, built once and cached: `dates` the posting dates in
        ascending order and `prefix[i]` the running signed balance through `dates[i]`. Postings sharing a
        date fold in together (their sum is order-independent), so any `through`/window query reduces to a
        bisect on `dates`. An account with no postings caches empty arrays."""
        cached = self._cumulative_by_account.get( account )
        if cached is not None:
            return cached
        postings = sorted( self._bookkeeper.postings( account ), key = lambda posting : posting.date )
        dates  : list = []
        prefix : list = []
        running = Decimal( '0' )
        for posting in postings:
            running += posting.signed_amount
            dates.append( posting.date )
            prefix.append( running )
            continue
        index = ( dates, prefix )
        self._cumulative_by_account[ account ] = index
        return index

    @staticmethod
    def _prefix_through( dates : list, prefix : list,
                         boundary : date, *, inclusive : bool ) -> Decimal:
        """The cumulative signed balance at `boundary`: the last prefix entry at or before it. `inclusive`
        counts a posting dated exactly `boundary` (a balance *through* a date); exclusive stops just before
        it (the opening side of a flow window). Zero when `boundary` precedes the first posting."""
        cut = ( bisect.bisect_right( dates, boundary ) if inclusive
                else bisect.bisect_left( dates, boundary ) )
        return prefix[ cut - 1 ] if cut > 0 else Decimal( '0' )
