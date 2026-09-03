"""The Explore economic-assumptions dials draw from the Economics *section* rates only -- the niche rates
and the Social Security funding what-if stay on the Advanced page, out of the Explore sandbox (#255).
Dialing a rate reaches the economics, leaving every other field intact."""
import unittest
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.planning.explore_sections import EconomicAssumptionsExploreForm


def _scenario() -> Scenario:
    return Scenario( assumptions = Assumptions(
        economics = EconomicParameters( inflation = Rate.percent( Decimal( '3' ) ) ) ) )


class ExploreEconomicSectionTests( SimpleTestCase ):

    def test_it_offers_the_economics_section_rates_only( self ):
        fields = set( EconomicAssumptionsExploreForm( scenario = _scenario() ).fields )
        self.assertIn( 'inflation', fields )
        self.assertIn( 'stock_appreciation', fields )
        self.assertNotIn( 'bond_appreciation', fields )                    # niche -> Advanced only
        self.assertNotIn( 'social_security_benefits_payable', fields )     # funding what-if -> Advanced only

    def test_dialing_a_rate_reaches_economics_and_leaves_the_rest( self ):
        scenario = _scenario()
        data     = QueryDict( mutable = True )
        data[ 'stock_appreciation' ] = '9'
        form = EconomicAssumptionsExploreForm( data, scenario = scenario )
        self.assertTrue( form.is_valid(), form.errors )
        economics = form.apply( scenario ).assumptions.economics
        self.assertEqual( economics.stock_appreciation, Rate.percent( Decimal( '9' ) ) )
        self.assertEqual( economics.inflation, Rate.percent( Decimal( '3' ) ) )   # untouched


if __name__ == '__main__':
    unittest.main()
