"""The external-factors section: the scenario's economic-factors copy and the tax projection.

§8 seeds the scenario's own copy of the economic rates from a library preset (Expected by default),
then lets the user edit any rate; the tax projection is shown as one more factor, defaulting to
COLA-indexed. Each rate is entered as a percent. The library preset is consulted only here (to seed
the copy) -- materialization reads the copy, not the library.
"""
from dataclasses import fields, replace
from decimal import Decimal

from django import forms

from common.rate import Rate

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile, TaxProjection

# Every rate factor of the engine's EconomicParameters (all of them, adjustable). The non-rate
# `window` is excluded -- it stays at its default, giving a constant outlook.
_FACTOR_NAMES = tuple(
    spec.name for spec in fields( EconomicParameters ) if isinstance( spec.default, Rate ) )


def default_economics() -> EconomicParameters:
    """The economic-factors copy a new scenario seeds with -- the Expected preset."""
    return economic_parameters( EconomicOutlookVariant.EXPECTED.label )


class ExternalFactorsForm( forms.Form ):
    """§8 -- the scenario's editable economic factors (seeded from a preset) and the tax projection
    (one more factor, defaulting to COLA-indexed). Each rate is entered as a percent; `apply` stores
    the factor copy and the tax forecast on the scenario."""

    tax_forecast_type = forms.ChoiceField(
        label = 'Tax brackets', choices = TaxForecastType.choices(),
        initial = TaxForecastType.COLA_INDEXED.name.lower() )

    def __init__( self, data = None, *, profile = None, scenario = None ):
        super().__init__( data, initial = self._initial( scenario ) )
        economics = self._seed( scenario )
        for name in _FACTOR_NAMES:
            field = forms.DecimalField( label = name.replace( '_', ' ' ).capitalize() )
            field.initial = getattr( economics, name ).fraction * Decimal( '100' )
            self.fields[ name ] = field

    @staticmethod
    def _seed( scenario ) -> EconomicParameters:
        if scenario is not None and scenario.economics is not None:
            return scenario.economics
        return default_economics()

    @staticmethod
    def _initial( scenario ) -> dict:
        if scenario is not None and scenario.tax_forecast is not None:
            return { 'tax_forecast_type': scenario.tax_forecast.tax_forecast_type.name.lower() }
        return dict()

    @property
    def factors( self ) -> list:
        return [ self[ name ] for name in _FACTOR_NAMES ]

    def apply( self, profile, scenario ):
        economics = EconomicParameters( **{
            name: Rate.percent( self.cleaned_data[ name ] ) for name in _FACTOR_NAMES } )
        tax_type = TaxForecastType.from_name( self.cleaned_data[ 'tax_forecast_type' ] )
        tax = TaxForecastProfile(
            tax_law_type = TaxLawType.US_FEDERAL, tax_forecast_type = tax_type,
            projection = self._projection( tax_type, economics ) )
        return profile, replace( scenario, economics = economics, tax_forecast = tax )

    @staticmethod
    def _projection( tax_type, economics ):
        """A COLA-indexed forecast indexes the tax figures at the economy's inflation -- the tax
        projection following the inflation factor; current law needs no projection."""
        if tax_type is TaxForecastType.COLA_INDEXED:
            return TaxProjection( cola_rate = economics.inflation )
        return None
