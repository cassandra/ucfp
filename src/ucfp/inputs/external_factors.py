"""The external-factors section: the assumptions' economic-factors copy and the tax projection.

§8 seeds the assumptions' own copy of the economic rates from a library preset (Expected by default),
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
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import StatuteProjection, TaxProjection

# Every rate factor of the engine's EconomicParameters (all of them, adjustable). The non-rate
# `window` is excluded -- it stays at its default, giving a constant outlook.
_FACTOR_NAMES = tuple(
    spec.name for spec in fields( EconomicParameters ) if isinstance( spec.default, Rate ) )


def default_economics() -> EconomicParameters:
    """The economic-factors copy a new Assumptions aggregate seeds with -- the Expected preset."""
    return economic_parameters( EconomicOutlookVariant.EXPECTED.label )


class ExternalFactorsForm( forms.Form ):
    """§8 -- the assumptions' editable economic factors (seeded from a preset) and the tax projection
    (one more factor, defaulting to COLA-indexed). Each rate is entered as a percent; `apply` stores
    the factor copy and the tax forecast on the assumptions."""

    forecast_type = forms.ChoiceField(
        label = 'Tax brackets', choices = StatuteForecastType.choices(),
        initial = StatuteForecastType.COLA_INDEXED.name.lower() )

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data, initial = self._initial( assumptions ) )
        economics = self._seed( assumptions )
        for name in _FACTOR_NAMES:
            field = forms.DecimalField( label = name.replace( '_', ' ' ).capitalize() )
            field.initial = getattr( economics, name ).fraction * Decimal( '100' )
            self.fields[ name ] = field

    @staticmethod
    def _seed( assumptions ) -> EconomicParameters:
        if assumptions is not None and assumptions.economics is not None:
            return assumptions.economics
        return default_economics()

    @staticmethod
    def _initial( assumptions ) -> dict:
        if assumptions is not None and assumptions.tax_projection is not None:
            return { 'forecast_type': assumptions.tax_projection.forecast_type.name.lower() }
        return dict()

    @property
    def factors( self ) -> list:
        return [ self[ name ] for name in _FACTOR_NAMES ]

    def apply( self, profile, assumptions ):
        economics = EconomicParameters( **{
            name: Rate.percent( self.cleaned_data[ name ] ) for name in _FACTOR_NAMES } )
        tax_type = StatuteForecastType.from_name( self.cleaned_data[ 'forecast_type' ] )
        tax_projection = TaxProjection(
            forecast_type = tax_type, projection = self._projection( tax_type, economics ) )
        return profile, replace(
            assumptions, economics = economics, tax_projection = tax_projection )

    @staticmethod
    def _projection( tax_type, economics ):
        """A COLA-indexed forecast indexes the tax figures at the economy's inflation -- the tax
        projection following the inflation factor; current law needs no projection."""
        if tax_type is StatuteForecastType.COLA_INDEXED:
            return StatuteProjection( cola_rate = economics.inflation )
        return None
