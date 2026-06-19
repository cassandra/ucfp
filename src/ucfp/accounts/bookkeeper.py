"""The Bookkeeper: the mechanisms over a `BooksOfAccount`.

Holds the books (the data) and supplies the operations -- building the chart forward,
recording balanced transactions, realizing gains, and enforcing the double-entry
invariants (which must hold for ephemeral books that are never persisted, so the
cross-entry balance rule lives here, not in a database constraint). It maintains an
in-memory postings index keyed by account *identity* (no pk needed), which the `Ledger`
view reads for balance queries.

The Bookkeeper is **persistence-ignorant** -- it imports no Django. Persisting a
`BooksOfAccount` is the Repository's job. The `Chart` and `Ledger` views are exposed for
convenience but own no state beyond the books and this index.

TRANSITIONAL: the `Ledger` view is defined here for now so the legacy `accounts/ledger.py`
(still used by `period`/`forecast`) can keep working alongside this new domain. It moves to
its own `accounts/ledger.py` once that legacy file is removed in the `period` cutover.
"""
from collections import namedtuple
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from .books import Account, BooksOfAccount, Entry, Transaction
from .chart import Chart
from .constants import DEFAULT_ROOT_ACCOUNT_NAMES
from .enums import AccountType, AssetClass, SideType, SystemAccountRole
from .exceptions import MissingAccountError, TransactionImbalanceError
from .money_utils import quantize_money


# One account's participation in one transaction, reduced to what balance queries need:
# the transaction's date and the entry's credit-positive signed magnitude.
_Posting = namedtuple( '_Posting', ( 'date', 'signed_amount' ) )


class Ledger:
    """The Ledger view: per-account balances over a `Bookkeeper`'s books.

    Reads the Bookkeeper's postings index; presents signed and natural balances, flows
    within a window, and the projection derivations `market_value` (cost + valuation
    companion) and `net_worth` (assets - liabilities). Uses a `Chart` for the structure
    those derivations need.
    """

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


class Bookkeeper:
    """Builds and queries a `BooksOfAccount` in memory; the authoritative invariant
    enforcer."""

    def __init__( self, books : Optional[ BooksOfAccount ] = None ):
        self._books = books if books is not None else BooksOfAccount()
        self._postings_by_account = dict()   # Account -> list[ _Posting ]
        for transaction in self._books.transactions:
            self._index( transaction )
            continue

    @property
    def books( self ) -> BooksOfAccount:
        return self._books

    @property
    def chart( self ) -> Chart:
        return Chart( self._books )

    @property
    def ledger( self ) -> Ledger:
        return Ledger( self )

    # -- chart construction --------------------------------------------------

    def build_standard_chart( self ) -> None:
        """Create the standard chart: one parentless root per AccountType, plus the
        Opening Balances and Unrealized Gains equity accounts beneath the Equity root."""
        roots = dict()
        for account_type in AccountType.all():
            root = self.add_account(
                Account( name = DEFAULT_ROOT_ACCOUNT_NAMES[ account_type ], account_type = account_type )
            )
            roots[ account_type ] = root
            continue
        for system_role in ( SystemAccountRole.OPENING_BALANCES, SystemAccountRole.UNREALIZED_GAINS ):
            self.add_account(
                Account(
                    name = system_role.label,
                    parent = roots[ AccountType.EQUITY ],
                    system_role = system_role,
                )
            )
            continue
        return

    def create_holding( self, parent : Account, name : str, asset_class : AssetClass ) -> Account:
        """Create an asset holding and, for classes that accrue unrealized gains, its
        companion valuation child. Market value = holding cost + valuation; the holding
        itself carries the cost basis."""
        holding = self.add_account( Account( name = name, parent = parent, asset_class = asset_class ) )
        if asset_class.accrues_unrealized_gains:
            self.add_account(
                Account( name = f'{name} (Valuation)', parent = holding, is_valuation = True )
            )
        return holding

    def add_account( self, account : Account ) -> Account:
        """Add `account` to the books and return it (its structure was validated on
        construction)."""
        self._books.accounts.append( account )
        return account

    # -- recording (invariant-enforcing) -------------------------------------

    def record( self,
                transaction_date : date,
                signed_postings  : Iterable[ tuple[ Account, Decimal ] ] ) -> Transaction:
        """Build and post a balanced transaction from (account, signed_amount) pairs
        (credit-positive); each entry's direction is derived from its sign. Zero-amount
        postings are skipped."""
        entries = list()
        for account, signed_amount in signed_postings:
            if signed_amount == 0:
                continue
            direction = SideType.CREDIT if signed_amount > 0 else SideType.DEBIT
            entries.append(
                Entry( account = account, amount = abs( signed_amount ), entry_direction = direction )
            )
            continue
        transaction = Transaction( transaction_date = transaction_date, entries = entries )
        self.post( transaction )
        return transaction

    def post( self, transaction : Transaction ) -> None:
        """Validate that `transaction` balances, hold it in the books, and index its
        postings. Raises on imbalance."""
        transaction.assert_balanced()
        self._books.transactions.append( transaction )
        self._index( transaction )
        return

    def realize( self,
                 holding               : Account,
                 proceeds              : Decimal,
                 *,
                 proceeds_account      : Account,
                 realized_gain_account : Account,
                 on_date               : date ) -> None:
        """Realize `proceeds` of `holding`'s market value into `proceeds_account`: draw
        down cost and valuation proportionally, recognize the realized gain (the valuation
        portion) into `realized_gain_account`, and reverse the Unrealized Gains equity.
        Net-worth-neutral -- the gain just moves from unrealized to realized (taxable).
        Caps at the holding's market value."""
        ledger = self.ledger
        market = ledger.market_value( holding )
        if market <= 0:
            return
        proceeds = quantize_money( min( proceeds, market ) )
        valuation_account = self.chart.valuation_of( holding )
        if valuation_account is None:
            cost_sold = proceeds
            gain = Decimal( '0' )
        else:
            fraction = proceeds / market
            cost_sold = quantize_money( ledger.natural_balance( holding ) * fraction )
            gain = proceeds - cost_sold
        postings = [ ( proceeds_account, -proceeds ), ( holding, cost_sold ) ]
        if gain != 0:
            unrealized_gain_account = self.chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
            if unrealized_gain_account is None:
                raise MissingAccountError( 'No Unrealized Gains equity account to realize against.' )
            postings += [
                ( valuation_account, gain ),
                ( unrealized_gain_account, -gain ),
                ( realized_gain_account, gain ),
            ]
        self.record( on_date, postings )
        return

    # -- invariants and index access -----------------------------------------

    def assert_balanced( self ) -> None:
        """Assert the whole books' signed entries sum to zero (every balanced transaction
        contributes zero, so any residual reveals malformed books)."""
        residual = sum(
            ( posting.signed_amount
              for postings in self._postings_by_account.values()
              for posting in postings ),
            Decimal( '0' ),
        )
        if residual != 0:
            raise TransactionImbalanceError( f'Books do not balance (residual {residual}).' )
        return

    def postings( self, account : Account ) -> tuple:
        """This account's held postings (date, signed_amount) -- the primitive the Ledger
        view reads. Empty for an account with no entries."""
        return tuple( self._postings_by_account.get( account, () ) )

    def _index( self, transaction : Transaction ) -> None:
        for entry in transaction.entries:
            posting = _Posting( date = transaction.transaction_date, signed_amount = entry.signed_amount )
            self._postings_by_account.setdefault( entry.account, list() ).append( posting )
            continue
        return
