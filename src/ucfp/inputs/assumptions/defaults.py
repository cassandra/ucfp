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
from decimal import Decimal

from common.rate import Rate

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.forecast.parameters import NetWorthCalculation, TransactionCosts
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import StatuteProjection, TaxProjection

from .schemas import Assumptions

# The tax forecast a new set (and the External Factors form) defaults to -- brackets tracking inflation.
DEFAULT_TAX_FORECAST_TYPE = StatuteForecastType.COLA_INDEXED

# A new set's default selling costs: a typical 6% realtor commission and $10,000 of fixed costs (title,
# escrow, transfer), the fixed amount in forecast-start dollars.
DEFAULT_REALTOR_FEE_RATE  = Rate.percent( Decimal( 6 ) )
DEFAULT_SALE_FIXED_COST   = Decimal( '10000' )


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


def default_transaction_costs() -> TransactionCosts:
    """The selling costs a new Assumptions set seeds with -- a 6% realtor fee and $10,000 fixed."""
    return TransactionCosts(
        property_sale_realtor_fee_rate = DEFAULT_REALTOR_FEE_RATE,
        property_sale_fixed_cost       = DEFAULT_SALE_FIXED_COST )


def default_net_worth_calculation() -> NetWorthCalculation:
    """The net-worth calculation a new Assumptions set seeds with -- zero latent-tax rates, so the
    Estimated Future Taxes overlay stays off until the user opts in by entering rates."""
    return NetWorthCalculation()


def default_assumptions() -> Assumptions:
    """A complete, runnable Assumptions set: the Expected economic outlook, a COLA-indexed tax projection
    at that outlook's inflation, default selling costs, and a net-worth calculation off by default --
    what a freshly minted set (and the form) starts from."""
    economics = default_economics()
    return Assumptions(
        economics = economics,
        tax_projection = tax_projection( DEFAULT_TAX_FORECAST_TYPE, economics ),
        transaction_costs = default_transaction_costs(),
        net_worth = default_net_worth_calculation() )
