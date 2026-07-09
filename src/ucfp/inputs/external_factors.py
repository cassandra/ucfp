"""The external-factors section: the assumptions' economic-factors copy and the tax projection.

§8 shows the assumptions' own copy of the economic rates (seeded from a library preset, Expected by
default) and lets the user edit any rate; the tax projection is shown as one more factor, defaulting
to COLA-indexed. Each rate is entered as a percent. The default seed and the tax-projection
composition are shared with minting through `assumptions.defaults` -- materialization reads the copy
stored here, not the library.
"""
from dataclasses import fields, replace
from decimal import Decimal

from django import forms

from common.rate import Rate

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.jurisdiction.enums import StatuteForecastType

from .assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE, default_economics, tax_projection

# Every rate factor of the engine's EconomicParameters (all of them, adjustable). The non-rate
# `window` is excluded -- it stays at its default, giving a constant outlook.
_FACTOR_NAMES = tuple(
    spec.name for spec in fields( EconomicParameters ) if isinstance( spec.default, Rate ) )


class ExternalFactorsForm( forms.Form ):
    """§8 -- the assumptions' editable economic factors (seeded from a preset) and the tax projection
    (one more factor, defaulting to COLA-indexed). Each rate is entered as a percent; `apply` stores
    the factor copy and the tax forecast on the assumptions."""

    forecast_type = forms.ChoiceField(
        label = 'Tax brackets', choices = StatuteForecastType.choices(),
        initial = DEFAULT_TAX_FORECAST_TYPE.name.lower() )

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
        return profile, replace(
            assumptions, economics = economics,
            tax_projection = tax_projection( tax_type, economics ) )


class ExternalFactorsSectionForm:
    """§8 section wrapper. The External Factors pane self-saves through `ExternalFactorsView`, so this
    section form only carries the flow: it always validates and its `apply` is a no-op, leaving Next to
    advance without re-saving. It exposes the editor (`factors_form`) for the pane to render -- the
    same shape the outer sections use (e.g. `LivingExpensesSectionForm`/`EventsForm`)."""

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        self._profile     = profile
        self._assumptions = assumptions

    def is_valid( self ) -> bool:
        return True

    @property
    def factors_form( self ) -> ExternalFactorsForm:
        return ExternalFactorsForm( profile = self._profile, assumptions = self._assumptions )

    def apply( self, profile, assumptions ):
        return profile, assumptions
