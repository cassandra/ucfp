"""Tests for the economic-outlook schedule resolution and asset-rate mapping (no DB).

The schedule windowing (which segment is in effect when, and the flat-zero fallback) and
the named-rate -> AssetClass mapping are foundational projection logic, so they get real
tests even under the phase's minimal-testing policy.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.dataclass_json import from_json_data
from common.date_window import DateWindow
from common.rate import FULL_RATE, Rate
from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters

FIVE_PERCENT = Rate( Decimal( '0.05' ) )
THREE_PERCENT = Rate( Decimal( '0.03' ) )


class BackCompatTests( unittest.TestCase ):
    """The funding-shortfall fields default so records written before they existed keep full benefits."""

    def test_json_without_the_funding_fields_deserializes_to_the_defaults( self ):
        # a pre-#243 EconomicParameters payload -- a rate, but no funding keys.
        economics = from_json_data( EconomicParameters, { 'inflation': { 'fraction': '0.03' } } )
        self.assertEqual( economics.inflation, Rate( Decimal( '0.03' ) ) )          # the stored rate survives
        self.assertEqual( economics.social_security_benefits_payable, FULL_RATE )   # 100% -> no reduction
        self.assertEqual( economics.social_security_reduction_year, 2032 )


class AssetRateMappingTests( unittest.TestCase ):

    def test_named_rates_map_to_asset_classes( self ):
        parameters = EconomicParameters(
            stock_appreciation           = FIVE_PERCENT,
            stock_dividend               = THREE_PERCENT,
            savings_interest             = THREE_PERCENT,
            precious_metals_appreciation = FIVE_PERCENT,
            collectibles_appreciation    = THREE_PERCENT,
            depreciation_rate            = FIVE_PERCENT,
        )
        rates = parameters.asset_rates()
        # stock appreciation drives both stock classes' growth
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
        self.assertEqual( rates.growth_rate( AssetClass.DIVIDEND_STOCKS ), FIVE_PERCENT )
        # precious metals and collectibles have their own (distinct) rates
        self.assertEqual( rates.growth_rate( AssetClass.PRECIOUS_METALS ), FIVE_PERCENT )
        self.assertEqual( rates.growth_rate( AssetClass.COLLECTIBLES ), THREE_PERCENT )
        # depreciation is the negative of the (positive) depreciation rate
        self.assertEqual( rates.growth_rate( AssetClass.DEPRECIATING ), Rate( Decimal( '-0.05' ) ) )
        # dividends and savings are distributions
        self.assertEqual( rates.distribution_rate( AssetClass.DIVIDEND_STOCKS ), THREE_PERCENT )
        self.assertEqual( rates.distribution_rate( AssetClass.CASH ), THREE_PERCENT )
        # a face-value class (cash) has no growth
        self.assertEqual( rates.growth_rate( AssetClass.CASH ), Rate( Decimal( '0' ) ) )

    def test_income_growth_rate_maps_classes( self ):
        parameters = EconomicParameters(
            wage_growth          = FIVE_PERCENT,
            social_security_cola = THREE_PERCENT,
        )
        self.assertEqual( parameters.income_growth_rate( IncomeTaxClass.WAGES ), FIVE_PERCENT )
        self.assertEqual( parameters.income_growth_rate( IncomeTaxClass.SOCIAL_SECURITY ), THREE_PERCENT )
        # a class with no stream growth (investment income is asset-driven) is flat
        self.assertEqual(
            parameters.income_growth_rate( IncomeTaxClass.LONG_TERM_GAINS ), Rate( Decimal( '0' ) ) )

    def test_expense_inflation_rate_splits_medical( self ):
        parameters = EconomicParameters( inflation = THREE_PERCENT, medical_inflation = FIVE_PERCENT )
        self.assertEqual( parameters.expense_inflation_rate( ExpenseTaxClass.MEDICAL ), FIVE_PERCENT )
        self.assertEqual( parameters.expense_inflation_rate( ExpenseTaxClass.LIVING ), THREE_PERCENT )


class ScheduleResolutionTests( unittest.TestCase ):

    def test_constant_applies_everywhere( self ):
        outlook = EconomicOutlook.constant( EconomicParameters( stock_appreciation = FIVE_PERCENT ) )
        for year in ( 2026, 2040, 2099 ):
            rates = outlook.asset_rates_at( date( year, 6, 1 ) )
            self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
            continue

    def test_segments_pin_rates_to_windows( self ):
        outlook = EconomicOutlook( Schedule( (
            EconomicParameters(
                window = DateWindow( end = date( 2030, 12, 31 ) ), stock_appreciation = FIVE_PERCENT ),
            EconomicParameters(
                window = DateWindow( start = date( 2031, 1, 1 ) ), stock_appreciation = THREE_PERCENT ),
        ) ) )
        self.assertEqual(
            outlook.asset_rates_at( date( 2028, 1, 1 ) ).growth_rate( AssetClass.STOCKS ), FIVE_PERCENT )
        self.assertEqual(
            outlook.asset_rates_at( date( 2035, 1, 1 ) ).growth_rate( AssetClass.STOCKS ), THREE_PERCENT )

    def test_gap_falls_back_to_flat_zero( self ):
        outlook = EconomicOutlook( Schedule( (
            EconomicParameters(
                window = DateWindow( start = date( 2031, 1, 1 ), end = date( 2040, 12, 31 ) ),
                stock_appreciation = FIVE_PERCENT ),
        ) ) )
        rates = outlook.asset_rates_at( date( 2026, 1, 1 ) )   # before any segment
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), Rate( Decimal( '0' ) ) )

    def test_empty_outlook_is_flat( self ):
        rates = EconomicOutlook().asset_rates_at( date( 2026, 1, 1 ) )
        self.assertEqual( rates.growth_rate( AssetClass.STOCKS ), Rate( Decimal( '0' ) ) )


if __name__ == '__main__':
    unittest.main()
