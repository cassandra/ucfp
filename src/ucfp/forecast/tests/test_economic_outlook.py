"""Tests for the economic-outlook schedule resolution and asset-rate mapping (no DB).

The schedule windowing (which segment is in effect when, and the flat-zero fallback) and
the named-rate -> AssetClass mapping are foundational projection logic, so they get real
tests even under the phase's minimal-testing policy.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters

FIVE_PERCENT = Rate( Decimal( '0.05' ) )
THREE_PERCENT = Rate( Decimal( '0.03' ) )


class AssetRateMappingTests( unittest.TestCase ):

    def test_named_rates_map_to_asset_classes( self ):
        parameters = EconomicParameters(
            stock_appreciation           = FIVE_PERCENT,
            stock_dividend               = THREE_PERCENT,
            savings_interest             = THREE_PERCENT,
            precious_metals_appreciation = FIVE_PERCENT,
            collectibles_appreciation    = THREE_PERCENT,
        )
        rates = parameters.asset_rates()
        # stock appreciation drives both stock classes' growth
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
        self.assertEqual( rates.growth_rate( AssetClass.DIVIDEND_STOCKS ), FIVE_PERCENT )
        # precious metals and collectibles have their own (distinct) rates
        self.assertEqual( rates.growth_rate( AssetClass.PRECIOUS_METALS ), FIVE_PERCENT )
        self.assertEqual( rates.growth_rate( AssetClass.COLLECTIBLES ), THREE_PERCENT )
        # dividends and savings are distributions
        self.assertEqual( rates.distribution_rate( AssetClass.DIVIDEND_STOCKS ), THREE_PERCENT )
        self.assertEqual( rates.distribution_rate( AssetClass.CASH ), THREE_PERCENT )
        # an unlisted class is flat
        self.assertEqual( rates.growth_rate( AssetClass.DEPRECIATING ), Rate( Decimal( '0' ) ) )


class ScheduleResolutionTests( unittest.TestCase ):

    def test_constant_applies_everywhere( self ):
        outlook = EconomicOutlook.constant( EconomicParameters( stock_appreciation = FIVE_PERCENT ) )
        for year in ( 2026, 2040, 2099 ):
            rates = outlook.asset_rates_at( date( year, 6, 1 ) )
            self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
            continue

    def test_segments_pin_rates_to_windows( self ):
        outlook = EconomicOutlook( segments = (
            EconomicParameters( end = date( 2030, 12, 31 ), stock_appreciation = FIVE_PERCENT ),
            EconomicParameters( start = date( 2031, 1, 1 ), stock_appreciation = THREE_PERCENT ),
        ) )
        self.assertEqual(
            outlook.asset_rates_at( date( 2028, 1, 1 ) ).growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
        self.assertEqual(
            outlook.asset_rates_at( date( 2035, 1, 1 ) ).growth_rate( AssetClass.STOCKS ), THREE_PERCENT )

    def test_gap_falls_back_to_flat_zero( self ):
        outlook = EconomicOutlook( segments = (
            EconomicParameters(
                start = date( 2031, 1, 1 ), end = date( 2040, 12, 31 ), stock_appreciation = FIVE_PERCENT ),
        ) )
        rates = outlook.asset_rates_at( date( 2026, 1, 1 ) )   # before any segment
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), Rate( Decimal( '0' ) ) )

    def test_empty_outlook_is_flat( self ):
        rates = EconomicOutlook().asset_rates_at( date( 2026, 1, 1 ) )
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), Rate( Decimal( '0' ) ) )


if __name__ == '__main__':
    unittest.main()
