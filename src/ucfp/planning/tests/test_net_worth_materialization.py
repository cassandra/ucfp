"""The Net Worth assumption (the latent-tax overlay rates) flows from Assumptions into
ForecastParameters, defaults to off, and survives JSON persistence (#177 phase 3)."""
import unittest
from decimal import Decimal

from common.dataclass_json import from_json_data, to_json_data
from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.forecast.parameters import NetWorthCalculation
from ucfp.inputs.assumptions.defaults import default_net_worth_calculation
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import Plans
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.planning.materialization import _net_worth_calculation, materialize
from ucfp.planning.tests.support import forecast_frame, forecast_profile

_D = Decimal
_RATES = NetWorthCalculation(
    ordinary_tax_rate = Rate.percent( _D( '24' ) ), capital_gains_tax_rate = Rate.percent( _D( '15' ) ) )


def _assumptions( net_worth ) -> Assumptions:
    return Assumptions(
        economics      = EconomicParameters(),
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ),
        net_worth      = net_worth )


class NetWorthCalculationExtractorTests( unittest.TestCase ):

    def test_present_rates_pass_through( self ):
        self.assertEqual( _net_worth_calculation( _assumptions( _RATES ) ), _RATES )

    def test_absent_defaults_to_off( self ):
        self.assertEqual( _net_worth_calculation( _assumptions( None ) ), NetWorthCalculation() )

    def test_default_builder_is_off( self ):
        self.assertEqual( default_net_worth_calculation(), NetWorthCalculation() )

    def test_survives_a_json_round_trip( self ):
        restored = from_json_data( Assumptions, to_json_data( _assumptions( _RATES ) ) )
        self.assertEqual( restored.net_worth, _RATES )


class NetWorthCalculationMaterializationTests( unittest.TestCase ):

    def test_rates_reach_forecast_parameters( self ):
        params = materialize( forecast_profile(), Plans(), _assumptions( _RATES ), forecast_frame() )
        self.assertEqual( params.net_worth_calculation, _RATES )

    def test_absent_materializes_to_off( self ):
        params = materialize( forecast_profile(), Plans(), _assumptions( None ), forecast_frame() )
        self.assertEqual( params.net_worth_calculation, NetWorthCalculation() )


if __name__ == '__main__':
    unittest.main()
