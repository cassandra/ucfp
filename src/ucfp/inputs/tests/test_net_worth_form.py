"""The Net Worth section form (#177 phase 4): it seeds the two latent-tax rates from the assumptions and
applies edits back, converting between the percent UI and the stored Rate. The section is registered in
the Assumptions flow right after Sales."""
import unittest
from decimal import Decimal

from common.rate import Rate
from ucfp.forecast.parameters import NetWorthCalculation
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.interview import SECTIONS
from ucfp.inputs.net_worth import NetWorthForm

_D = Decimal


def _assumptions( net_worth = None ) -> Assumptions:
    return Assumptions( net_worth = net_worth )


class NetWorthFormTests( unittest.TestCase ):

    def test_seeds_field_initials_from_the_assumptions_rates( self ):
        rates = NetWorthCalculation(
            ordinary_tax_rate = Rate.percent( _D( '24' ) ), capital_gains_tax_rate = Rate.percent( _D( '15' ) ) )
        form = NetWorthForm( assumptions = _assumptions( rates ) )
        self.assertEqual( form.fields[ 'ordinary_rate' ].initial, _D( '24' ) )
        self.assertEqual( form.fields[ 'capital_gains_rate' ].initial, _D( '15' ) )

    def test_seeds_zero_when_the_assumptions_have_no_net_worth( self ):
        form = NetWorthForm( assumptions = _assumptions( None ) )
        self.assertEqual( form.fields[ 'ordinary_rate' ].initial, _D( '0' ) )
        self.assertEqual( form.fields[ 'capital_gains_rate' ].initial, _D( '0' ) )

    def test_apply_stores_the_edited_rates_on_the_assumptions( self ):
        form = NetWorthForm( { 'ordinary_rate': '30', 'capital_gains_rate': '18' } )
        self.assertTrue( form.is_valid() )
        _profile, assumptions = form.apply( None, _assumptions() )
        self.assertEqual(
            assumptions.net_worth,
            NetWorthCalculation( ordinary_tax_rate = Rate.percent( _D( '30' ) ),
                                 capital_gains_tax_rate = Rate.percent( _D( '18' ) ) ) )


class NetWorthSectionRegistrationTests( unittest.TestCase ):

    def test_net_worth_follows_sales_in_the_assumptions_flow( self ):
        keys = [ section.key for section in SECTIONS ]
        self.assertIn( 'net-worth', keys )
        self.assertEqual( keys[ keys.index( 'transaction-costs' ) + 1 ], 'net-worth' )


if __name__ == '__main__':
    unittest.main()
