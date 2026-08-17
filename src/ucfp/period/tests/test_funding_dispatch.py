"""The cash-funding waterfall's liquidity dispatch and the residence sale handler (draw-order Phase 3).

The waterfall covers a shortfall by selling a slice of a liquid holding. A whole-asset source is
indivisible and sells whole through a dedicated handler instead. Step 1 stubbed every whole-asset
source (passed by, neither partially realized nor allowed to block a liquid source below it); step 3a
adds the residence handler -- reaching a residence sells it whole, books the proceeds to cash, and pays
off the mortgage it secures. The other whole-asset sources stay stubbed until their handlers land.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_span import DateSpan
from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, IncomeTaxClass, SystemAccountRole
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.period.parameters import AssetRates, FundingPolicy, PeriodParameters, PropertyData
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult

_D = Decimal


class FundingDispatchTests( unittest.TestCase ):

    def _books( self ):
        # Cash starts empty (below any positive floor), so the waterfall always has a shortfall to cover.
        # A §121 residence-gain revenue account is present so a residence sale can recognize its gain.
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart      = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        opening    = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        cash       = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
        bookkeeper.add_account( Account(
            name = 'Residence Gain', parent = chart.root( AccountType.REVENUE ),
            income_tax_class = IncomeTaxClass.RESIDENCE_SECTION_121_GAIN ) )
        return bookkeeper, asset_root, opening, cash

    def _seed( self, bookkeeper, opening, holding, value ):
        bookkeeper.record( date( 2030, 1, 1 ), [ ( holding, -value ), ( opening, value ) ] )

    def _seed_liability( self, bookkeeper, opening, account, balance ):
        bookkeeper.record( date( 2030, 1, 1 ), [ ( account, balance ), ( opening, -balance ) ] )

    def _fund( self, bookkeeper, draw_priority, floor, property_data = None ):
        parameters = PeriodParameters(
            date_span      = DateSpan( date( 2030, 1, 1 ), date( 2030, 12, 31 ) ),
            tax_context    = TaxContext( FilingStatus.SINGLE ),
            asset_rates    = AssetRates(),
            property_data  = property_data or dict(),
            funding_policy = FundingPolicy( cash_floor = floor, draw_priority = draw_priority ) )
        Period( parameters )._fund_to_target( bookkeeper, PeriodResult() )
        bookkeeper.assert_balanced()

    # ---- still-stubbed whole-asset sources (no handler yet) ----

    def test_an_unhandled_source_is_passed_by_not_partially_sold( self ):
        # Possessions have no handler yet, so the waterfall must leave them whole, not shave a slice.
        bookkeeper, asset_root, opening, cash = self._books()
        coins = bookkeeper.create_holding( asset_root, 'Gold', AssetClass.PRECIOUS_METALS )
        self._seed( bookkeeper, opening, coins, _D( '400000' ) )
        self._fund( bookkeeper, [ coins ], floor = _D( '10000' ) )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( coins ), _D( '400000' ) )    # untouched, not shaved to fund cash
        self.assertEqual( ledger.natural_balance( cash ), _D( '0' ) )       # so the shortfall is left unmet

    def test_an_unhandled_source_does_not_block_a_liquid_one_below_it( self ):
        # The possessions sit ahead of the CDs in priority; passing them by must not stop the CDs funding.
        bookkeeper, asset_root, opening, cash = self._books()
        coins = bookkeeper.create_holding( asset_root, 'Gold', AssetClass.PRECIOUS_METALS )
        cds   = bookkeeper.create_holding( asset_root, 'CDs', AssetClass.CDS )
        self._seed( bookkeeper, opening, coins, _D( '400000' ) )
        self._seed( bookkeeper, opening, cds, _D( '50000' ) )
        self._fund( bookkeeper, [ coins, cds ], floor = _D( '10000' ) )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( coins ), _D( '400000' ) )    # skipped
        self.assertEqual( ledger.natural_balance( cash ), _D( '10000' ) )   # funded to the floor from the CD
        self.assertEqual( ledger.market_value( cds ), _D( '40000' ) )       # which the CD covered

    # ---- the residence handler (3a) ----

    def test_the_residence_sells_whole_to_cover_a_shortfall( self ):
        bookkeeper, asset_root, opening, cash = self._books()
        home = bookkeeper.create_holding(
            asset_root, 'Home', AssetClass.REAL_ESTATE_RESIDENCE, handle = 'res' )
        self._seed( bookkeeper, opening, home, _D( '400000' ) )
        self._fund( bookkeeper, [ home ], floor = _D( '10000' ) )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( home ), _D( '0' ) )          # liquidated whole, not shaved
        self.assertEqual( ledger.natural_balance( cash ), _D( '400000' ) )  # the whole proceeds land in cash

    def test_the_residence_sale_pays_off_its_secured_mortgage( self ):
        bookkeeper, asset_root, opening, cash = self._books()
        home = bookkeeper.create_holding(
            asset_root, 'Home', AssetClass.REAL_ESTATE_RESIDENCE, handle = 'res' )
        mortgage = bookkeeper.add_account( Account(
            name = 'Mortgage', parent = bookkeeper.chart.root( AccountType.LIABILITY ), handle = 'mortgage' ) )
        self._seed( bookkeeper, opening, home, _D( '400000' ) )
        self._seed_liability( bookkeeper, opening, mortgage, _D( '300000' ) )
        self._fund( bookkeeper, [ home ], floor = _D( '10000' ),
                    property_data = { 'res' : PropertyData( mortgage_handles = ( 'mortgage', ) ) } )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( home ), _D( '0' ) )
        self.assertEqual( ledger.natural_balance( mortgage ), _D( '0' ) )     # mortgage cleared from the proceeds
        self.assertEqual( ledger.natural_balance( cash ), _D( '100000' ) )    # 400k proceeds - 300k mortgage

    def test_an_already_sold_residence_is_a_no_op( self ):
        # A residence liquidated to nothing has no value to draw, so reaching it again does nothing.
        bookkeeper, asset_root, opening, cash = self._books()
        home = bookkeeper.create_holding(
            asset_root, 'Home', AssetClass.REAL_ESTATE_RESIDENCE, handle = 'res' )
        self._fund( bookkeeper, [ home ], floor = _D( '10000' ) )   # home seeded to nothing
        self.assertEqual( bookkeeper.ledger.natural_balance( cash ), _D( '0' ) )


if __name__ == '__main__':
    unittest.main()
