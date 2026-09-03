"""The Economics editor (`ExternalFactorsForm`) and the Advanced page's Social Security funding editor
(`SocialSecurityFundingForm`), both in `external_factors` -- their taxonomy, seeding, round-tripping, and
the tax-projection recomposition that keeps a COLA-indexed projection tracking edited inflation.

The engine behaviour of the funding reduction is tested in `forecast/tests/test_income.py`; here we cover
the input layer -- that the knobs reach the stored economics unharmed and that the two forms compose the
same economics copy without clobbering each other's fields.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.date_window import DateWindow
from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE, tax_projection
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.external_factors import (
    ECONOMIC_FACTORS, AdvancedEconomicsForm, ExternalFactorsForm, SocialSecurityFundingForm )
from ucfp.jurisdiction.enums import StatuteForecastType

_PAYABLE = 'social_security_benefits_payable'
_YEAR    = 'social_security_reduction_year'

# The niche rates moved off the main Economics pane to the Advanced page's Economics subsection (#255).
_NICHE_RATES = { 'bond_appreciation', 'precious_metals_appreciation', 'collectibles_appreciation',
                 'depreciation_rate', 'rental_increase' }


def _seed() -> EconomicParameters:
    """A plain economics seed (zero rates, 100% benefits payable, 2032) -- avoids the DB-backed preset so
    the form logic is tested in isolation."""
    return EconomicParameters()


def _economics_post( economics, **overrides ) -> QueryDict:
    """A full valid POST for the Economics form, seeded from `economics`, with any field overridden. Only
    the economic rate fields the Economics form owns -- funding and the tax type live on other forms."""
    form = ExternalFactorsForm( assumptions = Assumptions( economics = economics ) )
    data = QueryDict( mutable = True )
    for name in form.fields:
        data[ name ] = str( getattr( economics, name ).fraction * 100 )
    for name, value in overrides.items():
        data[ name ] = str( value )
    return data


class EconomicFactorTaxonomyTests( SimpleTestCase ):
    """The Economics factors are grouped on a single 'what it applies to' axis (#255): the groups read in
    the intended order, the two historically mis-filed rates land in the right group, and the funding rate
    is off this pane yet still covered by the canonical rate list."""

    def _groups( self ) -> dict:
        form = ExternalFactorsForm( assumptions = Assumptions( economics = _seed() ) )
        return { group[ 'label' ]: [ row[ 'field' ].name for row in group[ 'factors' ] ]
                 for group in form.factor_groups }

    def test_groups_read_in_the_intended_order( self ):
        self.assertEqual(
            list( self._groups() ),
            [ 'Inflation', 'Growth & appreciation', 'Interest & yields', 'Income growth' ] )

    def test_medical_inflation_is_grouped_with_inflation( self ):
        self.assertIn( 'medical_inflation', self._groups()[ 'Inflation' ] )

    def test_niche_and_funding_rates_are_off_the_main_pane_but_in_the_canonical_list( self ):
        on_main   = { name for names in self._groups().values() for name in names }
        canonical = { factor.field for factor in ECONOMIC_FACTORS }
        for field in _NICHE_RATES | { _PAYABLE }:
            self.assertNotIn( field, on_main )     # off the main Economics pane
            self.assertIn( field, canonical )      # still a known rate (Explore + the completeness assert)


class EconomicsApplyTests( SimpleTestCase ):

    def test_apply_recomposes_the_cola_projection_at_the_edited_inflation( self ):
        # the Economics form does not show the tax type, but must keep a COLA-indexed projection indexed
        # at the current inflation, so an inflation edit here does not leave the projection stale.
        economics   = _seed()
        assumptions = Assumptions(
            economics = economics,
            tax_projection = tax_projection( StatuteForecastType.COLA_INDEXED, economics ) )
        form = ExternalFactorsForm( _economics_post( economics, inflation = 4 ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.economics.inflation, Rate.percent( Decimal( '4' ) ) )
        self.assertEqual( applied.tax_projection.projection.cola_rate, Rate.percent( Decimal( '4' ) ) )

    def test_apply_preserves_the_funding_knobs_it_does_not_edit( self ):
        economics   = EconomicParameters(
            social_security_benefits_payable = Rate.percent( Decimal( '75' ) ),
            social_security_reduction_year   = 2035 )
        assumptions = Assumptions( economics = economics )
        form = ExternalFactorsForm( _economics_post( economics, inflation = 2 ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.economics.social_security_benefits_payable, Rate.percent( Decimal( '75' ) ) )
        self.assertEqual( applied.economics.social_security_reduction_year, 2035 )

    def test_apply_preserves_the_niche_rates_it_does_not_edit( self ):
        # the niche rates left the main pane for Advanced; a main-pane save must not reset them to preset.
        economics   = EconomicParameters( bond_appreciation = Rate.percent( Decimal( '5' ) ) )
        assumptions = Assumptions( economics = economics )
        form = ExternalFactorsForm( _economics_post( economics, inflation = 2 ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.economics.bond_appreciation, Rate.percent( Decimal( '5' ) ) )

    def test_apply_keeps_a_stored_current_law_projection_frozen( self ):
        # recomposition reads the STORED forecast type: editing a rate must not manufacture a COLA
        # projection over a user's frozen-bracket (current-law) choice.
        economics   = _seed()
        assumptions = Assumptions(
            economics = economics,
            tax_projection = tax_projection( StatuteForecastType.CURRENT_LAW, economics ) )
        form = ExternalFactorsForm( _economics_post( economics, inflation = 4 ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.tax_projection.forecast_type, StatuteForecastType.CURRENT_LAW )
        self.assertIsNone( applied.tax_projection.projection )

    def test_apply_falls_back_to_the_default_projection_when_none_is_stored( self ):
        # the form no longer submits a tax type, so a save with none stored composes the default
        # (COLA-indexed) projection, indexed at the edited inflation.
        economics   = _seed()
        assumptions = Assumptions( economics = economics, tax_projection = None )
        form = ExternalFactorsForm( _economics_post( economics, inflation = 4 ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.tax_projection.forecast_type, DEFAULT_TAX_FORECAST_TYPE )
        self.assertEqual( applied.tax_projection.projection.cola_rate, Rate.percent( Decimal( '4' ) ) )

    def test_apply_preserves_the_unedited_window( self ):
        # apply replaces onto the seed rather than building fresh: fields the form never edits (the
        # outlook window) must survive a save.
        window      = DateWindow( start = date( 2030, 1, 1 ) )
        economics   = EconomicParameters( window = window )
        assumptions = Assumptions( economics = economics )
        form = ExternalFactorsForm( _economics_post( economics ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.economics.window, window )


class AdvancedEconomicsFormTests( SimpleTestCase ):
    """The Advanced page's Economics subsection edits only the niche rates on the same economics copy."""

    def test_it_offers_exactly_the_niche_rates( self ):
        form = AdvancedEconomicsForm( assumptions = Assumptions( economics = _seed() ) )
        self.assertEqual( set( form.fields ), _NICHE_RATES )

    def test_apply_edits_a_niche_rate_and_preserves_the_rest( self ):
        economics = EconomicParameters(
            inflation = Rate.percent( Decimal( '3' ) ),
            collectibles_appreciation = Rate.percent( Decimal( '1' ) ) )
        data = QueryDict( mutable = True )
        for name in _NICHE_RATES:
            data[ name ] = str( getattr( economics, name ).fraction * 100 )
        data[ 'collectibles_appreciation' ] = '4'
        form = AdvancedEconomicsForm( data, assumptions = Assumptions( economics = economics ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, Assumptions( economics = economics ) )
        self.assertEqual( assumptions.economics.collectibles_appreciation, Rate.percent( Decimal( '4' ) ) )
        self.assertEqual( assumptions.economics.inflation, Rate.percent( Decimal( '3' ) ) )   # untouched

    def test_apply_leaves_the_tax_projection_untouched( self ):
        economics   = _seed()
        projection  = tax_projection( StatuteForecastType.COLA_INDEXED, economics )
        assumptions = Assumptions( economics = economics, tax_projection = projection )
        data = QueryDict( mutable = True )
        for name in _NICHE_RATES:
            data[ name ] = '2'
        form = AdvancedEconomicsForm( data, assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.tax_projection, projection )


class SocialSecurityFundingFormTests( SimpleTestCase ):
    """The Advanced page's funding what-if edits the assumptions' economics copy in isolation."""

    def _apply( self, **overrides ):
        economics = _seed()
        data      = QueryDict( mutable = True )
        data[ _PAYABLE ] = str( economics.social_security_benefits_payable.fraction * 100 )
        data[ _YEAR ]    = str( economics.social_security_reduction_year )
        for name, value in overrides.items():
            data[ name ] = str( value )
        form = SocialSecurityFundingForm( data, assumptions = Assumptions( economics = economics ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, Assumptions( economics = economics ) )
        return assumptions.economics

    def test_it_seeds_the_funding_fields_from_economics( self ):
        form = SocialSecurityFundingForm( assumptions = Assumptions( economics = _seed() ) )
        self.assertEqual( form[ _PAYABLE ].value(), Decimal( '100' ) )   # whole percent, no decimals
        self.assertEqual( form[ _YEAR ].value(), 2032 )

    def test_it_round_trips_the_funding_fields_through_apply( self ):
        economics = self._apply( **{ _PAYABLE: 75, _YEAR: 2035 } )
        self.assertEqual( economics.social_security_benefits_payable, Rate.percent( Decimal( '75' ) ) )
        self.assertEqual( economics.social_security_reduction_year, 2035 )

    def test_apply_preserves_the_rate_factors_it_does_not_edit( self ):
        economics = EconomicParameters( inflation = Rate.percent( Decimal( '3' ) ) )
        data      = QueryDict( mutable = True )
        data[ _PAYABLE ] = '80'
        data[ _YEAR ]    = '2032'
        form = SocialSecurityFundingForm( data, assumptions = Assumptions( economics = economics ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, Assumptions( economics = economics ) )
        self.assertEqual( assumptions.economics.inflation, Rate.percent( Decimal( '3' ) ) )      # untouched
        self.assertEqual( assumptions.economics.social_security_benefits_payable, Rate.percent( Decimal( '80' ) ) )

    def test_apply_leaves_the_tax_projection_untouched( self ):
        # funding does not edit inflation, so it must not recompose the projection (unlike the main pane).
        economics   = _seed()
        projection  = tax_projection( StatuteForecastType.COLA_INDEXED, economics )
        assumptions = Assumptions( economics = economics, tax_projection = projection )
        form = SocialSecurityFundingForm(
            QueryDict( f'{_PAYABLE}=80&{_YEAR}=2032' ), assumptions = assumptions )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, applied = form.apply( None, assumptions )
        self.assertEqual( applied.tax_projection, projection )

    def test_benefits_payable_is_bounded_to_0_100( self ):
        for bad in ( 150, -10 ):
            form = SocialSecurityFundingForm(
                QueryDict( f'{_PAYABLE}={bad}&{_YEAR}=2032' ),
                assumptions = Assumptions( economics = _seed() ) )
            self.assertFalse( form.is_valid() )
            self.assertIn( _PAYABLE, form.errors )

    def test_the_effective_year_is_bounded( self ):
        form = SocialSecurityFundingForm(
            QueryDict( f'{_PAYABLE}=100&{_YEAR}=1999' ),
            assumptions = Assumptions( economics = _seed() ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( _YEAR, form.errors )


if __name__ == '__main__':
    unittest.main()
