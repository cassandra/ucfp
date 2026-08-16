"""The cash-funding waterfall's liquidity dispatch (draw-order Phase 3, step 1).

The waterfall covers a cash shortfall by selling a slice of a liquid holding. Real estate and
possessions are indivisible: they are sold whole through a dedicated sale handler (a later step), not
shaved to the exact shortfall. Until that handler exists the waterfall must simply pass such a source
by -- it is neither partially realized (which would wrongly sell a fraction of a house) nor allowed to
block a liquid source further down the order.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_span import DateSpan
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.period.parameters import AssetRates, FundingPolicy, PeriodParameters
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult

_D = Decimal


class FundingDispatchTests( unittest.TestCase ):

    def _books( self ):
        # Cash starts empty (below any positive floor), so the waterfall always has a shortfall to cover.
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart      = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        opening    = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        cash       = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
        return bookkeeper, asset_root, opening, cash

    def _seed( self, bookkeeper, opening, holding, value ):
        bookkeeper.record( date( 2030, 1, 1 ), [ ( holding, -value ), ( opening, value ) ] )

    def _fund( self, bookkeeper, draw_priority, floor ):
        parameters = PeriodParameters(
            date_span      = DateSpan( date( 2030, 1, 1 ), date( 2030, 12, 31 ) ),
            tax_context    = TaxContext( FilingStatus.SINGLE ),
            asset_rates    = AssetRates(),
            funding_policy = FundingPolicy( cash_floor = floor, draw_priority = draw_priority ) )
        Period( parameters )._fund_to_target( bookkeeper, PeriodResult() )
        bookkeeper.assert_balanced()

    def test_an_indivisible_source_is_passed_by_not_partially_sold( self ):
        bookkeeper, asset_root, opening, cash = self._books()
        home = bookkeeper.create_holding( asset_root, 'Home', AssetClass.REAL_ESTATE_RESIDENCE )
        self._seed( bookkeeper, opening, home, _D( '400000' ) )
        self._fund( bookkeeper, [ home ], floor = _D( '10000' ) )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( home ), _D( '400000' ) )    # untouched, not shaved to fund cash
        self.assertEqual( ledger.natural_balance( cash ), _D( '0' ) )      # so the shortfall is left unmet

    def test_an_indivisible_source_does_not_block_a_liquid_one_below_it( self ):
        # The home sits ahead of the CDs in priority; passing it by must not stop the CDs from funding.
        bookkeeper, asset_root, opening, cash = self._books()
        home = bookkeeper.create_holding( asset_root, 'Home', AssetClass.REAL_ESTATE_RESIDENCE )
        cds  = bookkeeper.create_holding( asset_root, 'CDs', AssetClass.CDS )
        self._seed( bookkeeper, opening, home, _D( '400000' ) )
        self._seed( bookkeeper, opening, cds, _D( '50000' ) )
        self._fund( bookkeeper, [ home, cds ], floor = _D( '10000' ) )
        ledger = bookkeeper.ledger
        self.assertEqual( ledger.market_value( home ), _D( '400000' ) )    # skipped
        self.assertEqual( ledger.natural_balance( cash ), _D( '10000' ) )  # funded to the floor from the CD
        self.assertEqual( ledger.market_value( cds ), _D( '40000' ) )      # which the CD covered


if __name__ == '__main__':
    unittest.main()
