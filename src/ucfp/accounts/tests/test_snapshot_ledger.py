"""Tests for `SnapshotLedger` -- the immutable-books read view that precomputes cumulative balances.

The optimization must be behaviourally invisible: over a fixed books, a `SnapshotLedger` must return
exactly what the live `Ledger` returns for every balance and flow query. So the live Ledger (the linear
re-scan) is the oracle here, and these cases assert the two agree across the boundary cases a bisect can
get wrong -- dates before the first posting, exactly on a posting, between postings, on a date several
postings share, and after the last -- plus that each account's index is built only once. The domain
imports no Django, so these are plain `unittest` cases.
"""
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, IncomeTaxClass, SystemAccountRole


# Posting dates chosen so 2027-01-01 carries two transactions -- the same-date fold a naive scan and a
# bisect must agree on.
_D1 = date( 2026, 1, 1 )
_D2 = date( 2026, 6, 15 )
_D3 = date( 2027, 1, 1 )
_D4 = date( 2028, 3, 10 )

# Probe dates spanning every boundary case: before the first posting, on it, between, on the shared
# date, on the last, and after. `None` (the whole history) is probed separately.
_PROBE_DATES = [ date( 2025, 12, 31 ), _D1, date( 2026, 3, 1 ), _D2, _D3, _D4, date( 2029, 1, 1 ) ]

# Flow windows exercising inclusive edges (a window whose bounds land exactly on posting dates), an empty
# window before any activity, and a window strictly between postings.
_PROBE_WINDOWS = [ ( _D1, _D4 ), ( _D1, date( 2026, 12, 31 ) ), ( _D2, _D3 ),
                   ( date( 2025, 1, 1 ), date( 2025, 12, 31 ) ), ( date( 2026, 1, 2 ), _D2 ) ]


def _seed_books() -> Bookkeeper:
    """A bookkeeper whose journal exercises the interesting shapes: an asset holding with a valuation
    companion (so `market_value` folds two accounts), a same-date pair of postings, an untouched account
    (empty index), and revenue/expense flow accounts."""
    bookkeeper = Bookkeeper()
    bookkeeper.build_standard_chart()
    chart      = bookkeeper.chart
    asset_root = chart.root( AccountType.ASSET )
    revenue    = chart.root( AccountType.REVENUE )
    expense    = chart.root( AccountType.EXPENSE )
    cash    = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
    stocks  = bookkeeper.create_holding( asset_root, 'Brokerage', AssetClass.STOCKS )
    wages   = bookkeeper.add_account( _child( revenue, 'Wages', IncomeTaxClass.WAGES ) )
    grocery = bookkeeper.add_account( _child( expense, 'Groceries' ) )
    # An account with no postings, so its index is empty -- the zero-balance edge.
    bookkeeper.create_holding( asset_root, 'Untouched', AssetClass.CASH )
    opening    = chart.system_account( SystemAccountRole.OPENING_BALANCES )
    valuation  = chart.valuation_of( stocks )
    unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )

    bookkeeper.record( _D1, [ ( cash, Decimal( '-100000' ) ), ( stocks, Decimal( '-400000' ) ),
                              ( opening, Decimal( '500000' ) ) ], description = 'Opening' )
    bookkeeper.record( _D2, [ ( cash, Decimal( '3000' ) ), ( wages, Decimal( '-3000' ) ) ],
                       description = 'Paycheck' )
    # Two transactions dated _D3: a spend and a market appreciation -- the same-date fold.
    bookkeeper.record( _D3, [ ( cash, Decimal( '250' ) ), ( grocery, Decimal( '-250' ) ) ],
                       description = 'Groceries' )
    bookkeeper.record( _D3, [ ( valuation, Decimal( '-40000' ) ), ( unrealized, Decimal( '40000' ) ) ],
                       description = 'Appreciation' )
    bookkeeper.record( _D4, [ ( cash, Decimal( '1200' ) ), ( wages, Decimal( '-1200' ) ) ],
                       description = 'Paycheck' )
    return bookkeeper


def _child( parent, name, income_tax_class = None ):
    """A leaf account under a type root (type is inherited, so a child must not set it)."""
    return Account( name = name, parent = parent, income_tax_class = income_tax_class )


class SnapshotLedgerEquivalenceTests( unittest.TestCase ):
    """A `SnapshotLedger` agrees with the live `Ledger` on every query over the same books."""

    def setUp( self ):
        self.bookkeeper = _seed_books()
        self.live       = self.bookkeeper.ledger
        self.snapshot   = self.bookkeeper.snapshot_ledger
        self.accounts   = self.bookkeeper.books.accounts

    def test_signed_balance_matches_across_boundary_dates( self ):
        for account in self.accounts:
            for through in [ None ] + _PROBE_DATES:
                self.assertEqual(
                    self.snapshot.signed_balance( account, through = through ),
                    self.live.signed_balance( account, through = through ),
                    msg = f'{account.name} through {through}' )

    def test_natural_balance_matches_across_boundary_dates( self ):
        for account in self.accounts:
            for through in [ None ] + _PROBE_DATES:
                self.assertEqual(
                    self.snapshot.natural_balance( account, through = through ),
                    self.live.natural_balance( account, through = through ),
                    msg = f'{account.name} through {through}' )

    def test_flows_match_across_windows( self ):
        for account in self.accounts:
            for start, end in _PROBE_WINDOWS:
                self.assertEqual(
                    self.snapshot.flows( account, start = start, end = end ),
                    self.live.flows( account, start = start, end = end ),
                    msg = f'{account.name} [{start}, {end}]' )

    def test_market_value_and_net_worth_match( self ):
        holdings = list( self.snapshot._chart.holdings() )
        for through in [ None ] + _PROBE_DATES:
            for holding in holdings:
                self.assertEqual(
                    self.snapshot.market_value( holding, through = through ),
                    self.live.market_value( holding, through = through ),
                    msg = f'market_value {holding.name} through {through}' )
            self.assertEqual(
                self.snapshot.net_worth( through = through ),
                self.live.net_worth( through = through ),
                msg = f'net_worth through {through}' )


class SnapshotLedgerIndexTests( unittest.TestCase ):
    """The cumulative index is a build-once cache, and the snapshot is a point-in-time view."""

    def test_index_built_once_per_account( self ):
        bookkeeper = _seed_books()
        snapshot   = bookkeeper.snapshot_ledger
        cash       = next( account for account in bookkeeper.books.accounts if account.name == 'Cash' )
        with patch.object( bookkeeper, 'postings', wraps = bookkeeper.postings ) as spy:
            for _ in range( 10 ):
                snapshot.signed_balance( cash, through = _D3 )
                snapshot.flows( cash, start = _D1, end = _D4 )
                continue
        cash_reads = [ call for call in spy.call_args_list if call.args and call.args[ 0 ] is cash ]
        self.assertEqual( len( cash_reads ), 1 )

    def test_snapshot_is_point_in_time( self ):
        """The snapshot reflects the books as of its first read of an account: a posting added after
        that read is not seen (the immutable-books contract). The live ledger, by contrast, would see
        it -- which is why the engine keeps the live ledger."""
        bookkeeper = _seed_books()
        snapshot   = bookkeeper.snapshot_ledger
        cash       = next( account for account in bookkeeper.books.accounts if account.name == 'Cash' )
        opening    = bookkeeper.chart.system_account( SystemAccountRole.OPENING_BALANCES )
        before     = snapshot.signed_balance( cash )               # first read -- fixes the snapshot
        bookkeeper.record( date( 2030, 1, 1 ),
                           [ ( cash, Decimal( '500' ) ), ( opening, Decimal( '-500' ) ) ] )
        self.assertEqual( snapshot.signed_balance( cash ), before )
        self.assertEqual( bookkeeper.ledger.signed_balance( cash ), before + Decimal( '500' ) )


if __name__ == '__main__':
    unittest.main()
