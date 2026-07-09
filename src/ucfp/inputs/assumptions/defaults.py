"""The default content a new Assumptions set starts from -- one source of truth shared by minting and
the External Factors form.

Minting seeds a new set from `default_assumptions` so it is complete and runnable immediately (rather
than an empty shell the user must open a form to populate); the External Factors form seeds its own
display and reset baseline from the same builders and composes an edited set through `tax_projection`.
Kept apart from the form module so the repository can seed a new set without depending on `django.forms`,
and so mint and form cannot drift on what "default" means.

The economic-factors copy is the Expected library preset; the tax projection defaults to COLA-indexed
at that outlook's inflation.
"""
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import StatuteProjection, TaxProjection

from .schemas import Assumptions

# The tax forecast a new set (and the External Factors form) defaults to -- brackets tracking inflation.
DEFAULT_TAX_FORECAST_TYPE = StatuteForecastType.COLA_INDEXED


def default_economics() -> EconomicParameters:
    """The economic-factors copy a new Assumptions set seeds with -- the Expected preset."""
    return economic_parameters( EconomicOutlookVariant.EXPECTED.label )


def tax_projection(
        forecast_type : StatuteForecastType, economics : EconomicParameters ) -> TaxProjection:
    """The tax projection for a chosen forecast type under `economics`: a COLA-indexed forecast indexes
    the tax figures at the economy's inflation; current law needs no projection knobs. The single place
    that composes a `TaxProjection`, used by both the default seed and the form's applied edit."""
    projection = ( StatuteProjection( cola_rate = economics.inflation )
                   if forecast_type is StatuteForecastType.COLA_INDEXED else None )
    return TaxProjection( forecast_type = forecast_type, projection = projection )


def default_assumptions() -> Assumptions:
    """A complete, runnable Assumptions set: the Expected economic outlook and a COLA-indexed tax
    projection at that outlook's inflation -- what a freshly minted set (and the form) starts from."""
    economics = default_economics()
    return Assumptions(
        economics = economics,
        tax_projection = tax_projection( DEFAULT_TAX_FORECAST_TYPE, economics ) )
