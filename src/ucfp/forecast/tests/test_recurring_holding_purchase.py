"""RecurringHoldingPurchase: the engine expands a recurring holding acquisition itself, inflating the
price to each occurrence's year -- so a replacement's cost tracks inflation over the horizon instead of
being baked flat into the materialized inputs. With `trade_in` it first realizes the whole existing
holding (a car swap); without it, a plain recurring investment. Tax follows the holding's own class, so
the one path serves depreciating and appreciating holdings with no special-casing.

Occurrences land on their exact dates (here Jan 1, as real vehicle purchases do), and the engine applies
each period's depreciation on the opening value before the period's events -- so a holding bought this
year sits at full price at year-end and erodes from the next year on.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, RecurringHoldingPurchase, Subject )
from ucfp.forecast.tests.granularity_harness import ANNUAL, MONTHLY, run_at
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


def _params( *, end : date, economics : EconomicParameters, purchases : list,
             holding_class : AssetClass = AssetClass.DEPRECIATING,
             cash : str = '200000' ) -> ForecastParameters:
    """A minimal run: a cash hub to fund the buys and one target holding opening at zero (filled by the
    purchases, as a materialized vehicle holding is), plus whatever economic rates the case needs."""
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end,
        filing_status = FilingStatus.SINGLE,
        statute       = _STATUTE,
        subjects      = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( cash ), Decimal( cash ), handle = 'cash' ),
            AssetParameters( 'Holding', holding_class, Decimal( '0' ), Decimal( '0' ), handle = 'holding' ) ],
        economic_outlook = EconomicOutlook.constant( economics ),
        recurring_holding_purchases = purchases )


def _one( **fields ) -> RecurringHoldingPurchase:
    defaults = dict( holding = 'holding', interval = Duration( 1, TimeUnit.YEAR ) )
    defaults.update( fields )
    return RecurringHoldingPurchase( **defaults )


class RecurringHoldingPurchaseTests( unittest.TestCase ):

    def test_price_inflates_to_each_occurrences_year( self ):
        # 10% inflation, no depreciation: the 2027 buy costs x1.1 and the 2028 buy x1.21, accumulating.
        params = _params(
            end       = date( 2028, 12, 31 ),
            economics = EconomicParameters( inflation = Rate( Decimal( '0.10' ) ) ),
            purchases = [ _one( price = Decimal( '10000' ),
                                window = DateWindow( start = date( 2027, 1, 1 ) ) ) ] )
        reader  = Bookkeeper( Forecast( params ).run().books )
        ledger  = reader.ledger
        holding = reader.chart.account( 'holding' )
        cash    = reader.chart.account( 'cash' )
        self.assertEqual( ledger.market_value( holding, through = date( 2027, 12, 31 ) ), Decimal( '11000' ) )
        self.assertEqual( ledger.market_value( holding, through = date( 2028, 12, 31 ) ), Decimal( '23100' ) )
        # cash fell by exactly the nominal prices paid (11,000 + 12,100)
        self.assertEqual( ledger.market_value( cash, through = date( 2028, 12, 31 ) ), Decimal( '176900' ) )

    def test_the_first_occurrence_at_the_forecast_start_is_uninflated( self ):
        # The start-year factor is 1.0, so a purchase at t0 posts the today's-dollars price unchanged.
        params = _params(
            end       = date( 2026, 12, 31 ),
            economics = EconomicParameters( inflation = Rate( Decimal( '0.10' ) ) ),
            purchases = [ _one( price = Decimal( '10000' ),
                                window = DateWindow( start = date( 2026, 1, 1 ) ) ) ] )
        reader  = Bookkeeper( Forecast( params ).run().books )
        holding = reader.chart.account( 'holding' )
        self.assertEqual( reader.ledger.market_value( holding, through = date( 2026, 12, 31 ) ),
                          Decimal( '10000' ) )

    def test_trade_in_swaps_the_whole_depreciated_holding_tax_free( self ):
        # 20%/yr depreciation, no inflation, replaced every 3 years from 2026. Each replacement trades the
        # whole depreciated holding in to cash and rebuys at 30,000; between times it just erodes.
        params = _params(
            end       = date( 2029, 12, 31 ),
            economics = EconomicParameters( depreciation_rate = Rate( Decimal( '0.20' ) ) ),
            purchases = [ _one( price = Decimal( '30000' ), interval = Duration( 3, TimeUnit.YEAR ),
                                window = DateWindow( start = date( 2026, 1, 1 ) ), trade_in = True ) ] )
        reader  = Bookkeeper( Forecast( params ).run().books )
        reader.assert_balanced()
        ledger  = reader.ledger
        holding = reader.chart.account( 'holding' )
        # bought 2026 (full price at year-end), then declining-balance 30k -> 24k -> 19.2k, replaced 2029.
        self.assertEqual( ledger.market_value( holding, through = date( 2026, 12, 31 ) ), Decimal( '30000' ) )
        self.assertEqual( ledger.market_value( holding, through = date( 2027, 12, 31 ) ), Decimal( '24000' ) )
        self.assertEqual( ledger.market_value( holding, through = date( 2028, 12, 31 ) ), Decimal( '19200' ) )
        self.assertEqual( ledger.market_value( holding, through = date( 2029, 12, 31 ) ), Decimal( '30000' ) )
        # net worth fell only by the real depreciation (the trade-in loss is TAX_FREE, so no tax leaks):
        # 6,000 (2027) + 4,800 (2028) + 3,840 (2029) = 14,640 off the opening 200,000.
        self.assertEqual( ledger.net_worth( through = date( 2029, 12, 31 ) ), Decimal( '185360' ) )

    def test_without_trade_in_it_is_a_plain_recurring_investment( self ):
        # An appreciating holding (STOCKS) through the very same path -- no trade-in, no special-casing.
        # With no growth, three 5,000 buys accumulate to 15,000 and net worth is unchanged (a cash->asset
        # swap, not an expense; no realization means no tax).
        params = _params(
            end           = date( 2028, 12, 31 ),
            economics     = EconomicParameters(),
            purchases     = [ _one( price = Decimal( '5000' ),
                                    window = DateWindow( start = date( 2026, 1, 1 ) ) ) ],
            holding_class = AssetClass.STOCKS )
        reader  = Bookkeeper( Forecast( params ).run().books )
        ledger  = reader.ledger
        holding = reader.chart.account( 'holding' )
        cash    = reader.chart.account( 'cash' )
        self.assertEqual( ledger.market_value( holding, through = date( 2028, 12, 31 ) ), Decimal( '15000' ) )
        self.assertEqual( ledger.market_value( cash, through = date( 2028, 12, 31 ) ), Decimal( '185000' ) )
        self.assertEqual( ledger.net_worth( through = date( 2028, 12, 31 ) ), Decimal( '200000' ) )

    def test_annual_and_monthly_runs_agree( self ):
        # Granularity invariance of what this primitive controls -- occurrence placement and the
        # annual-indexed price inflation. The holding does not depreciate here: per-period asset growth
        # on a mid-forecast acquisition is granularity-sensitive in the engine independently of this
        # feature (a Jan-1 buy escapes its buy-year depreciation only at the annual grain), so that
        # interaction is left to the annual grain the app runs vehicles at.
        params = _params(
            end       = date( 2035, 12, 31 ),
            economics = EconomicParameters( inflation = Rate( Decimal( '0.03' ) ) ),
            purchases = [ _one( price = Decimal( '30000' ), interval = Duration( 3, TimeUnit.YEAR ),
                                window = DateWindow( start = date( 2027, 1, 1 ) ), trade_in = True ) ] )
        annual   = Bookkeeper( run_at( params, ANNUAL ).books )
        monthly  = Bookkeeper( run_at( params, MONTHLY ).books )
        holdings = ( annual.chart.account( 'holding' ), monthly.chart.account( 'holding' ) )
        cashes   = ( annual.chart.account( 'cash' ), monthly.chart.account( 'cash' ) )
        for year in range( 2026, 2036 ):
            through = date( year, 12, 31 )
            self.assertEqual( annual.ledger.market_value( holdings[ 0 ], through = through ),
                              monthly.ledger.market_value( holdings[ 1 ], through = through ),
                              msg = f'{year}: holding value annual vs monthly' )
            self.assertEqual( annual.ledger.market_value( cashes[ 0 ], through = through ),
                              monthly.ledger.market_value( cashes[ 1 ], through = through ),
                              msg = f'{year}: cash annual vs monthly' )
            continue


if __name__ == '__main__':
    unittest.main()
