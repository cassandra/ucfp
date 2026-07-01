"""Tests for COLA indexing of the tax parameters.

The projection scales the inflation-indexed figures (brackets, standard deduction, contribution
limits, the Social Security wage base, the ACA poverty guideline) by a cumulative COLA factor,
while the figures Congress fixed in statute (SS taxability thresholds, the NIIT and Additional
Medicare thresholds, the capital-loss cap, the section 121 exclusion, the SALT cap, the
passive-activity allowance) stay put -- so they bite harder over time. Rates, ratios, and ages
never move. The projection is smooth (no statutory rounding increments).
"""
import unittest
from decimal import Decimal

from common.rate import Rate
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, Statute, StatuteProjection, TaxProjection
from ucfp.jurisdiction.us.parameters import BASE_YEAR, federal_2025

_SINGLE = FilingStatus.SINGLE


class TaxParameterIndexingTests( unittest.TestCase ):

    def setUp( self ):
        self.base    = federal_2025()
        self.factor  = Decimal( '1.5' )
        self.indexed = self.base.indexed( self.factor )

    def test_indexed_dollar_figures_scale( self ):
        self.assertEqual(                                              # ordinary bracket bound
            self.indexed.ordinary_brackets[ _SINGLE ].rows[ 1 ][ 0 ],
            self.base.ordinary_brackets[ _SINGLE ].rows[ 1 ][ 0 ] * self.factor )
        self.assertEqual(                                              # LTCG bracket bound
            self.indexed.ltcg_brackets[ _SINGLE ].rows[ 1 ][ 0 ],
            self.base.ltcg_brackets[ _SINGLE ].rows[ 1 ][ 0 ] * self.factor )
        self.assertEqual(                                              # standard deduction
            self.indexed.standard_deduction[ _SINGLE ].base,
            self.base.standard_deduction[ _SINGLE ].base * self.factor )
        self.assertEqual(                                              # contribution limit
            self.indexed.contribution_limits.elective_deferral,
            self.base.contribution_limits.elective_deferral * self.factor )
        self.assertEqual(                                              # SS wage base
            self.indexed.fica_rules.ss_wage_base,
            self.base.fica_rules.ss_wage_base * self.factor )
        self.assertEqual(                                              # ACA poverty guideline
            self.indexed.aca.poverty_first_person,
            self.base.aca.poverty_first_person * self.factor )

    def test_statutory_thresholds_stay_fixed( self ):
        self.assertEqual(
            self.indexed.ss_thresholds[ _SINGLE ].base, self.base.ss_thresholds[ _SINGLE ].base )
        self.assertEqual(
            self.indexed.niit_thresholds[ _SINGLE ], self.base.niit_thresholds[ _SINGLE ] )
        self.assertEqual(
            self.indexed.fica_rules.additional_medicare_thresholds[ _SINGLE ],
            self.base.fica_rules.additional_medicare_thresholds[ _SINGLE ] )
        self.assertEqual( self.indexed.capital_loss_offset_cap, self.base.capital_loss_offset_cap )
        self.assertEqual(
            self.indexed.section_121_exclusion[ _SINGLE ], self.base.section_121_exclusion[ _SINGLE ] )
        self.assertEqual( self.indexed.itemized_rules.salt_cap, self.base.itemized_rules.salt_cap )
        self.assertEqual(
            self.indexed.passive_activity.loss_allowance, self.base.passive_activity.loss_allowance )

    def test_rates_and_ages_stay_fixed( self ):
        self.assertEqual(                                             # a bracket rate, not its bound
            self.indexed.ordinary_brackets[ _SINGLE ].rows[ 1 ][ 1 ],
            self.base.ordinary_brackets[ _SINGLE ].rows[ 1 ][ 1 ] )
        self.assertEqual( self.indexed.niit_rate, self.base.niit_rate )
        self.assertEqual( self.indexed.fica_rules.ss_rate, self.base.fica_rules.ss_rate )
        self.assertEqual(
            self.indexed.contribution_limits.catch_up_age,
            self.base.contribution_limits.catch_up_age )


class StatuteProjectionTests( unittest.TestCase ):

    def _engine( self, forecast_type, year, cola = None ):
        projection = StatuteProjection( cola_rate = cola ) if cola is not None else None
        profile = StatuteProfile(
            JurisdictionType.US_FEDERAL, TaxProjection( forecast_type, projection = projection ) )
        return Statute( profile ).engine_for( year )

    def test_current_law_is_static_across_years( self ):
        engine = self._engine( StatuteForecastType.CURRENT_LAW, BASE_YEAR + 50 )
        self.assertEqual(
            engine._parameters.fica_rules.ss_wage_base, federal_2025().fica_rules.ss_wage_base )

    def test_cola_indexed_compounds_from_the_base_year( self ):
        engine = self._engine(
            StatuteForecastType.COLA_INDEXED, BASE_YEAR + 2, cola = Rate( Decimal( '0.10' ) ) )
        self.assertEqual(
            engine._parameters.fica_rules.ss_wage_base,
            federal_2025().fica_rules.ss_wage_base * Decimal( '1.10' ) ** 2 )

    def test_cola_indexed_at_the_base_year_is_unchanged( self ):
        engine = self._engine(
            StatuteForecastType.COLA_INDEXED, BASE_YEAR, cola = Rate( Decimal( '0.10' ) ) )
        self.assertEqual(
            engine._parameters.fica_rules.ss_wage_base, federal_2025().fica_rules.ss_wage_base )

    def test_cola_indexed_without_a_rate_is_rejected( self ):
        with self.assertRaises( ValueError ):
            self._engine( StatuteForecastType.COLA_INDEXED, BASE_YEAR + 1 )


if __name__ == '__main__':
    unittest.main()
