"""The Taxes section of the Advanced page: the future tax-bracket projection.

The projection chooses whether future brackets track inflation (COLA-indexed, the default) or freeze at
today's levels; it is composed through `assumptions.defaults.tax_projection`, which indexes a COLA-indexed
forecast at the outlook's inflation (read from the stored economics). The net-worth latent-tax estimate is
a separate concern -- an adjustment to reported net worth, not a tax setting -- and lives in its own
Net worth calculation section (`net_worth.py`).
"""
from dataclasses import replace

from django import forms

from ucfp.jurisdiction.enums import StatuteForecastType

from .assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE, seed_economics, tax_projection


class TaxesForm( forms.Form ):
    """The Advanced Taxes editor: the future-tax-bracket forecast type. `apply` recomposes the tax
    projection (COLA-indexed at the outlook's inflation) and stores it back on the assumptions."""

    forecast_type = forms.ChoiceField(
        label = 'Future tax brackets', choices = StatuteForecastType.choices(),
        initial = DEFAULT_TAX_FORECAST_TYPE.name.lower(),
        widget = forms.Select( attrs = { 'class' : 'custom-select w-auto' } ) )

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data, initial = self._initial( assumptions ) )

    @staticmethod
    def _initial( assumptions ) -> dict:
        if assumptions is not None and assumptions.tax_projection is not None:
            return { 'forecast_type': assumptions.tax_projection.forecast_type.name.lower() }
        return dict()

    def apply( self, profile, assumptions ):
        # The COLA-indexed projection is indexed at the outlook's inflation, so recompose it from the
        # stored economics (the assumptions' own, or the default).
        tax_type = StatuteForecastType.from_name( self.cleaned_data[ 'forecast_type' ] )
        return profile, replace(
            assumptions, tax_projection = tax_projection( tax_type, seed_economics( assumptions ) ) )
