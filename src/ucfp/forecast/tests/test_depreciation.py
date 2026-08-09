"""Test that a depreciating asset (a vehicle) loses value over the forecast."""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, Subject
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection


class DepreciationTests( unittest.TestCase ):

    def test_depreciating_asset_loses_value_each_year( self ):
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Car', AssetClass.DEPRECIATING, Decimal( '30000' ), Decimal( '30000' ),
                                 handle = 'car' ) ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( depreciation_rate = Rate( Decimal( '0.20' ) ) ) ),
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        car = reader.chart.account( 'car' )
        # declining-balance: 30000 -> 24000 -> 19200 (loses 20% of the remaining value each year)
        self.assertEqual( ledger.market_value( car, through = date( 2026, 12, 31 ) ), Decimal( '24000' ) )
        self.assertEqual( ledger.market_value( car, through = date( 2027, 12, 31 ) ), Decimal( '19200' ) )


if __name__ == '__main__':
    unittest.main()
