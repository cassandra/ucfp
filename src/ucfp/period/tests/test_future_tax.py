"""Unit tests for the Estimated Future Taxes foundation (#177): the per-holding classifier/estimate and
the to-target re-estimate that books the liability. These pin the two easy-to-invert pieces -- which
asset classes are taxed at which rate, and that the sweep is idempotent and self-correcting -- without a
full forecast run. Nothing in the engine calls the sweep yet (that is phase 2)."""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate, ZERO_RATE
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.period.future_tax import (
    estimated_future_tax, future_tax_rate, reestimate_future_taxes )

_D           = Decimal
_SEED_DATE   = date( 2026, 1, 1 )
_ORDINARY    = Rate.percent( _D( '24' ) )   # 0.24
_CAPGAINS    = Rate.percent( _D( '15' ) )   # 0.15

_ORDINARY_CLASSES = { AssetClass.PRETAX_RETIREMENT }
_CAPGAINS_CLASSES = {
    AssetClass.STOCKS, AssetClass.DIVIDEND_STOCKS, AssetClass.BONDS,
    AssetClass.REAL_ESTATE_RENTAL, AssetClass.REAL_ESTATE_SECOND_HOME }


def _books() -> Bookkeeper:
    bookkeeper = Bookkeeper()
    bookkeeper.build_standard_chart()
    return bookkeeper


def _seed_holding( bookkeeper, name, asset_class, market_value, cost_basis ):
    """Create `asset_class` holding seeded to `market_value` with `cost_basis` -- the cost in the
    holding account, the embedded gain in its valuation companion (mirrors the forecast's opening
    postings), so `market_value - cost_basis` reads back as the taxable amount."""
    chart   = bookkeeper.chart
    holding = bookkeeper.create_holding( chart.root( AccountType.ASSET ), name, asset_class )
    opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
    if cost_basis != 0:
        bookkeeper.record( _SEED_DATE, [ ( holding, -cost_basis ), ( opening, cost_basis ) ] )
    embedded_gain = market_value - cost_basis
    if embedded_gain != 0:
        valuation        = chart.valuation_of( holding )
        unrealized_gains = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        bookkeeper.record( _SEED_DATE, [ ( valuation, -embedded_gain ), ( unrealized_gains, embedded_gain ) ] )
    return holding


class FutureTaxRateTests( unittest.TestCase ):

    def test_each_asset_class_maps_to_its_latent_rate( self ):
        for asset_class in AssetClass:
            with self.subTest( asset_class = asset_class ):
                expected = ( _ORDINARY if asset_class in _ORDINARY_CLASSES
                             else _CAPGAINS if asset_class in _CAPGAINS_CLASSES
                             else ZERO_RATE )
                self.assertEqual(
                    future_tax_rate( asset_class, _ORDINARY, _CAPGAINS ), expected )


class EstimatedFutureTaxTests( unittest.TestCase ):

    def test_pretax_taxes_the_whole_balance_at_the_ordinary_rate( self ):
        bookkeeper = _books()
        ira = _seed_holding( bookkeeper, 'IRA', AssetClass.PRETAX_RETIREMENT, _D( '200000' ), _D( '0' ) )
        self.assertEqual(
            estimated_future_tax( ira, bookkeeper.ledger, _ORDINARY, _CAPGAINS ), _D( '48000' ) )

    def test_taxable_taxes_only_the_unrealized_gain_at_the_capgains_rate( self ):
        bookkeeper = _books()
        stocks = _seed_holding( bookkeeper, 'Brokerage', AssetClass.STOCKS, _D( '130000' ), _D( '100000' ) )
        self.assertEqual(   # 30k gain x 15%
            estimated_future_tax( stocks, bookkeeper.ledger, _ORDINARY, _CAPGAINS ), _D( '4500' ) )

    def test_excluded_classes_estimate_nothing( self ):
        bookkeeper = _books()
        roth      = _seed_holding( bookkeeper, 'Roth', AssetClass.ROTH, _D( '200000' ), _D( '0' ) )
        residence = _seed_holding(
            bookkeeper, 'Home', AssetClass.REAL_ESTATE_RESIDENCE, _D( '500000' ), _D( '300000' ) )
        metals    = _seed_holding( bookkeeper, 'Gold', AssetClass.PRECIOUS_METALS, _D( '50000' ), _D( '20000' ) )
        for holding in ( roth, residence, metals ):
            with self.subTest( holding = holding.name ):
                self.assertEqual(
                    estimated_future_tax( holding, bookkeeper.ledger, _ORDINARY, _CAPGAINS ), _D( '0' ) )

    def test_an_unrealized_loss_is_floored_at_zero( self ):
        bookkeeper = _books()
        stocks = _seed_holding( bookkeeper, 'Brokerage', AssetClass.STOCKS, _D( '80000' ), _D( '100000' ) )
        self.assertEqual(   # value below basis -> no tax benefit credited
            estimated_future_tax( stocks, bookkeeper.ledger, _ORDINARY, _CAPGAINS ), _D( '0' ) )


class ReestimateFutureTaxesTests( unittest.TestCase ):

    def _seeded( self ) -> Bookkeeper:
        bookkeeper = _books()
        _seed_holding( bookkeeper, 'IRA', AssetClass.PRETAX_RETIREMENT, _D( '200000' ), _D( '0' ) )
        _seed_holding( bookkeeper, 'Brokerage', AssetClass.STOCKS, _D( '130000' ), _D( '100000' ) )
        return bookkeeper

    def test_books_the_target_and_reduces_net_worth( self ):
        bookkeeper = self._seeded()
        ledger = bookkeeper.ledger
        before = ledger.net_worth()
        reestimate_future_taxes( bookkeeper, _ORDINARY, _CAPGAINS, _SEED_DATE )
        liability = bookkeeper.chart.system_account( SystemAccountRole.ESTIMATED_FUTURE_TAXES )
        self.assertEqual( ledger.natural_balance( liability ), _D( '52500' ) )   # 48000 + 4500
        self.assertEqual( ledger.net_worth(), before - _D( '52500' ) )
        bookkeeper.assert_balanced()

    def test_is_idempotent_when_balances_are_unchanged( self ):
        bookkeeper = self._seeded()
        reestimate_future_taxes( bookkeeper, _ORDINARY, _CAPGAINS, _SEED_DATE )
        transaction_count = len( bookkeeper.books.transactions )
        reestimate_future_taxes( bookkeeper, _ORDINARY, _CAPGAINS, _SEED_DATE )   # nothing new to book
        self.assertEqual( len( bookkeeper.books.transactions ), transaction_count )

    def test_releases_as_a_balance_is_drawn_down( self ):
        bookkeeper = self._seeded()
        reestimate_future_taxes( bookkeeper, _ORDINARY, _CAPGAINS, _SEED_DATE )
        # Draw $100k out of the IRA to cash: its taxable balance falls 200k -> 100k.
        chart = bookkeeper.chart
        cash  = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        ira = next( holding for holding in chart.holdings() if holding.name == 'IRA' )
        bookkeeper.record(
            date( 2027, 1, 1 ), [ ( cash, -_D( '100000' ) ), ( chart.valuation_of( ira ), _D( '100000' ) ) ] )
        reestimate_future_taxes( bookkeeper, _ORDINARY, _CAPGAINS, date( 2027, 1, 1 ) )
        liability = chart.system_account( SystemAccountRole.ESTIMATED_FUTURE_TAXES )
        self.assertEqual(   # 100k x 24% + 30k x 15%
            bookkeeper.ledger.natural_balance( liability ), _D( '28500' ) )
        bookkeeper.assert_balanced()

    def test_zero_rates_book_nothing( self ):
        bookkeeper = self._seeded()
        reestimate_future_taxes( bookkeeper, ZERO_RATE, ZERO_RATE, _SEED_DATE )
        liability = bookkeeper.chart.system_account( SystemAccountRole.ESTIMATED_FUTURE_TAXES )
        self.assertEqual( bookkeeper.ledger.natural_balance( liability ), _D( '0' ) )
        self.assertFalse(
            any( txn.description == 'Estimated future tax re-estimate'
                 for txn in bookkeeper.books.transactions ) )


if __name__ == '__main__':
    unittest.main()
