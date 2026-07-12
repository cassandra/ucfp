"""Tests for the pure-Python double-entry domain (no database).

The structural invariants and the balance/realization arithmetic are ground truth for the
whole model, so they are tested even under the phase's minimal-testing policy. The domain
imports no Django, so these are plain `unittest` cases.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    IncomeTaxClass,
    SideType,
    SystemAccountRole,
)
from ucfp.accounts.exceptions import AccountStructureError, TransactionImbalanceError

OPENING = date( 2026, 1, 1 )
LATER   = date( 2026, 6, 1 )


def _seed_books():
    """A bookkeeper with the standard chart, a cash and a stock holding, an LT-gains
    revenue account, and a $500k opening cost in the stock holding."""
    bookkeeper = Bookkeeper()
    bookkeeper.build_standard_chart()
    chart = bookkeeper.chart
    asset_root = chart.root( AccountType.ASSET )
    revenue_root = chart.root( AccountType.REVENUE )
    cash = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
    stocks = bookkeeper.create_holding( asset_root, 'Brokerage', AssetClass.STOCKS )
    lt_gains = bookkeeper.add_account(
        Account( name = 'LT Gains', parent = revenue_root, income_tax_class = IncomeTaxClass.LONG_TERM_GAINS )
    )
    opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
    bookkeeper.record( OPENING, [ ( stocks, Decimal( '-500000' ) ), ( opening, Decimal( '500000' ) ) ] )
    return bookkeeper, cash, stocks, lt_gains


class AccountStructureTests( unittest.TestCase ):

    def test_root_requires_account_type( self ):
        with self.assertRaises( AccountStructureError ):
            Account( name = 'Bad root' )

    def test_non_root_must_not_set_account_type( self ):
        root = Account( name = 'Assets', account_type = AccountType.ASSET )
        with self.assertRaises( AccountStructureError ):
            Account( name = 'Child', parent = root, account_type = AccountType.ASSET )

    def test_asset_class_only_on_asset_account( self ):
        equity_root = Account( name = 'Equity', account_type = AccountType.EQUITY )
        with self.assertRaises( AccountStructureError ):
            Account( name = 'Weird', parent = equity_root, asset_class = AssetClass.STOCKS )

    def test_effective_type_and_normal_side_inherited( self ):
        root = Account( name = 'Assets', account_type = AccountType.ASSET )
        child = Account( name = 'Brokerage', parent = root, asset_class = AssetClass.STOCKS )
        self.assertEqual( child.effective_account_type, AccountType.ASSET )
        self.assertEqual( child.account_normal_type, SideType.DEBIT )


class BookkeeperTests( unittest.TestCase ):

    def test_imbalanced_transaction_rejected( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        with self.assertRaises( TransactionImbalanceError ):
            bookkeeper.record( LATER, [ ( stocks, Decimal( '100' ) ) ] )

    def test_create_holding_valuation_companion( self ):
        bookkeeper, cash, stocks, _lt_gains = _seed_books()
        chart = bookkeeper.chart
        self.assertIsNotNone( chart.valuation_of( stocks ) )   # appreciating -> companion
        self.assertIsNone( chart.valuation_of( cash ) )        # cash -> none

    def test_opening_balance_and_net_worth( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.natural_balance( stocks ), Decimal( '500000' ) )
        self.assertEqual( ledger.net_worth(), Decimal( '500000' ) )
        bookkeeper.assert_balanced()

    def test_growth_lifts_market_value_not_cost( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        chart, ledger = bookkeeper.chart, bookkeeper.ledger
        valuation = chart.valuation_of( stocks )
        unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record(
            LATER, [ ( valuation, Decimal( '-100000' ) ), ( unrealized, Decimal( '100000' ) ) ] )
        self.assertEqual( ledger.natural_balance( stocks ), Decimal( '500000' ) )   # cost unchanged
        self.assertEqual( ledger.market_value( stocks ), Decimal( '600000' ) )      # cost + valuation
        self.assertEqual( ledger.net_worth(), Decimal( '600000' ) )

    def test_through_date_excludes_later_postings( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        chart, ledger = bookkeeper.chart, bookkeeper.ledger
        valuation = chart.valuation_of( stocks )
        unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record(
            LATER, [ ( valuation, Decimal( '-100000' ) ), ( unrealized, Decimal( '100000' ) ) ] )
        self.assertEqual( ledger.market_value( stocks, through = OPENING ), Decimal( '500000' ) )
        self.assertEqual( ledger.market_value( stocks, through = LATER ), Decimal( '600000' ) )

    def test_realize_is_networth_neutral_and_recognizes_gain( self ):
        bookkeeper, cash, stocks, lt_gains = _seed_books()
        chart, ledger = bookkeeper.chart, bookkeeper.ledger
        valuation = chart.valuation_of( stocks )
        unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record(
            LATER, [ ( valuation, Decimal( '-100000' ) ), ( unrealized, Decimal( '100000' ) ) ] )
        bookkeeper.realize(
            stocks, Decimal( '60000' ),
            proceeds_account = cash, realized_gain_account = lt_gains, on_date = LATER,
        )
        self.assertEqual( ledger.natural_balance( cash ), Decimal( '60000' ) )      # proceeds landed
        self.assertEqual( ledger.market_value( stocks ), Decimal( '540000' ) )      # 10% drawn down
        self.assertEqual( ledger.natural_balance( lt_gains ), Decimal( '10000' ) )  # gain recognized
        self.assertEqual( ledger.net_worth(), Decimal( '600000' ) )                 # unchanged
        bookkeeper.assert_balanced()


class JournalTests( unittest.TestCase ):
    """The results-page drill-down: the plain per-account journal, and the market-value fold that
    combines a holding with its valuation companion so the running balance tracks market value --
    the same fold the Ledger applies to the holding's results column."""

    def test_account_journal_lists_only_that_accounts_postings( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        chart      = bookkeeper.chart
        valuation  = chart.valuation_of( stocks )
        unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record(                                          # appreciation lands in the companion
            LATER, [ ( valuation, Decimal( '-100000' ) ), ( unrealized, Decimal( '100000' ) ) ] )
        rows = bookkeeper.journal.account_entries( stocks )
        self.assertEqual( len( rows ), 1 )                          # the holding sees only its cost basis
        self.assertEqual( rows[ -1 ].balance, Decimal( '500000' ) )

    def test_market_value_journal_folds_valuation_and_tracks_market_value( self ):
        bookkeeper, _cash, stocks, _lt_gains = _seed_books()
        chart, ledger = bookkeeper.chart, bookkeeper.ledger
        valuation  = chart.valuation_of( stocks )
        unrealized = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record(
            LATER, [ ( valuation, Decimal( '-100000' ) ), ( unrealized, Decimal( '100000' ) ) ] )
        rows = bookkeeper.journal.market_value_entries( stocks, valuation )
        self.assertEqual( len( rows ), 2 )                          # opening cost, then the appreciation
        self.assertEqual( rows[ 0 ].balance, Decimal( '500000' ) )  # market value after the opening
        self.assertEqual( rows[ -1 ].balance, ledger.market_value( stocks ) )   # folds to market value
        self.assertEqual( rows[ -1 ].balance, Decimal( '600000' ) )
        self.assertIn( 'Unrealized Gains', rows[ -1 ].counterparts )
        self.assertNotIn( 'Valuation', rows[ -1 ].counterparts )    # the folded companion is not a counterpart


if __name__ == '__main__':
    unittest.main()
