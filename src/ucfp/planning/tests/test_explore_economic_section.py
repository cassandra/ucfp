"""The Explore economic-assumptions dials share the External Factors bounds: the Social Security
benefits-payable dial is a bounded 0-100 share there too (not an open-ended rate), and dialing it
reaches the economics without disturbing the effective year (which is edited only in §8)."""
import unittest
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.planning.explore_sections import EconomicAssumptionsExploreForm

_PAYABLE = 'social_security_benefits_payable'


def _scenario() -> Scenario:
    return Scenario( assumptions = Assumptions(
        economics = EconomicParameters( social_security_reduction_year = 2032 ) ) )


def _dial( value ) -> QueryDict:
    data = QueryDict( mutable = True )
    data[ _PAYABLE ] = str( value )
    return data


class ExploreBenefitsPayableTests( SimpleTestCase ):

    def test_the_benefits_payable_dial_is_bounded_to_0_100( self ):
        form = EconomicAssumptionsExploreForm( _dial( 150 ), scenario = _scenario() )
        self.assertFalse( form.is_valid() )                     # a share over 100% is rejected, as in §8
        self.assertIn( _PAYABLE, form.errors )

    def test_dialing_benefits_payable_reaches_economics_and_leaves_the_year( self ):
        scenario = _scenario()
        form     = EconomicAssumptionsExploreForm( _dial( 75 ), scenario = scenario )
        self.assertTrue( form.is_valid(), form.errors )
        economics = form.apply( scenario ).assumptions.economics
        self.assertEqual( economics.social_security_benefits_payable, Rate.percent( Decimal( '75' ) ) )
        self.assertEqual( economics.social_security_reduction_year, 2032 )   # year is §8-only, untouched


if __name__ == '__main__':
    unittest.main()
