"""The Net worth calculation editor (`NetWorthForm`): it seeds the two latent-tax rates from the
assumptions and applies edits back, converting between the percent UI and the stored Rate. The section is
the last subsection of the Advanced Assumptions page (#255)."""
import unittest
from decimal import Decimal

from common.rate import Rate
from ucfp.forecast.parameters import NetWorthCalculation
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.net_worth import NetWorthForm

_D = Decimal


def _assumptions( net_worth = None ) -> Assumptions:
    return Assumptions( net_worth = net_worth )


class NetWorthFormTests( unittest.TestCase ):

    def test_field_labels_flag_the_rates_as_latent_estimates( self ):
        form = NetWorthForm( assumptions = _assumptions() )
        self.assertEqual( form.fields[ 'ordinary_rate' ].label, 'Latent ordinary tax rate' )
        self.assertEqual( form.fields[ 'capital_gains_rate' ].label, 'Latent capital-gains tax rate' )

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


if __name__ == '__main__':
    unittest.main()
