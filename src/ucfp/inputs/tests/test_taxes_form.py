"""The Advanced page's Taxes editor (`TaxesForm`): it seeds the tax-bracket forecast type from the
assumptions and recomposes the tax projection at the outlook's inflation on apply. Also that the Advanced
section replaced the two thin Assumptions steps in the interview spine (#255)."""
import unittest

from django.http import QueryDict

from common.rate import Rate
from decimal import Decimal
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.defaults import tax_projection
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.interview import SECTIONS
from ucfp.inputs.taxes import TaxesForm
from ucfp.jurisdiction.enums import StatuteForecastType

_D = Decimal


def _assumptions( *, forecast_type = None, inflation = '3' ) -> Assumptions:
    economics = EconomicParameters( inflation = Rate.percent( _D( inflation ) ) )
    projection = tax_projection( forecast_type, economics ) if forecast_type is not None else None
    return Assumptions( economics = economics, tax_projection = projection )


def _post( forecast_type ) -> QueryDict:
    return QueryDict( f'forecast_type={forecast_type.name.lower()}' )


class TaxesFormSeedTests( unittest.TestCase ):

    def test_seeds_the_forecast_type_from_the_assumptions( self ):
        form = TaxesForm( assumptions = _assumptions( forecast_type = StatuteForecastType.CURRENT_LAW ) )
        self.assertEqual( form[ 'forecast_type' ].value(), 'current_law' )

    def test_has_no_net_worth_fields( self ):
        # the latent-tax rates moved to their own Net worth calculation section (#255)
        form = TaxesForm( assumptions = _assumptions() )
        self.assertNotIn( 'ordinary_rate', form.fields )
        self.assertNotIn( 'capital_gains_rate', form.fields )


class TaxesFormApplyTests( unittest.TestCase ):

    def test_apply_composes_a_cola_projection_indexed_at_the_outlook_inflation( self ):
        form = TaxesForm( _post( StatuteForecastType.COLA_INDEXED ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, _assumptions( inflation = '5' ) )
        self.assertEqual( assumptions.tax_projection.forecast_type, StatuteForecastType.COLA_INDEXED )
        self.assertEqual( assumptions.tax_projection.projection.cola_rate, Rate.percent( _D( '5' ) ) )

    def test_apply_current_law_has_no_projection_knobs( self ):
        form = TaxesForm( _post( StatuteForecastType.CURRENT_LAW ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, _assumptions() )
        self.assertEqual( assumptions.tax_projection.forecast_type, StatuteForecastType.CURRENT_LAW )
        self.assertIsNone( assumptions.tax_projection.projection )


class AdvancedSectionRegistrationTests( unittest.TestCase ):

    def test_advanced_replaces_the_two_thin_steps_and_ends_the_flow( self ):
        keys = [ section.key for section in SECTIONS ]
        self.assertIn( 'advanced', keys )
        self.assertNotIn( 'transaction-costs', keys )      # folded into Advanced
        self.assertNotIn( 'net-worth', keys )              # folded into Advanced
        self.assertEqual( keys[ keys.index( 'external-factors' ) + 1 ], 'advanced' )


if __name__ == '__main__':
    unittest.main()
