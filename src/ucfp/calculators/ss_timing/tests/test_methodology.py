"""The methodology explanation: the SSA terms and values for a strategy, and the login-free modal that
shows them. The statutory values come from the jurisdiction facade (tested there); here we cover that the
right terms are listed with sensible values, and that the modal is reachable and keyed to the strategy.
"""
import json
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from ucfp.calculators.ss_timing.compute import Claimant
from ucfp.calculators.ss_timing.methodology import methodology


class MethodologyTermsTest( SimpleTestCase ):

    def test_a_couple_lists_both_earners_plus_spousal_and_survivor( self ):
        earners = ( Claimant( 'Higher', 1960, Decimal( '3000' ), 85 ),
                    Claimant( 'Lower', 1960, Decimal( '1000' ), 88 ) )
        by_symbol = { term.symbol: term.value for term in methodology( earners, ( 67, 67 ) ) }
        self.assertIn( 'PIA_h', by_symbol )
        self.assertIn( 'PIA_l', by_symbol )
        # At full retirement age the monthly benefit equals the PIA and there is no reduction.
        self.assertEqual( by_symbol[ 'MB_h' ], '$3,000/mo' )
        self.assertEqual( by_symbol[ 'R_h' ], '0.0%' )
        self.assertEqual( by_symbol[ 'MB_s' ], '$500/mo' )         # spousal excess: half 3000, less 1000
        self.assertEqual( by_symbol[ 'MB_surv' ], '$3,000/mo' )    # survivor: the larger own benefit

    def test_an_early_single_claim_shows_a_reduction_and_no_couple_terms( self ):
        solo      = ( Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ), )
        by_symbol = { term.symbol: term.value for term in methodology( solo, ( 62, ) ) }
        self.assertTrue( by_symbol[ 'R' ].startswith( '-' ) )      # claiming at 62 reduces the benefit
        self.assertNotIn( 'MB_s', by_symbol )
        self.assertNotIn( 'MB_surv', by_symbol )

    def test_delaying_shows_a_positive_credit( self ):
        solo      = ( Claimant( 'Solo', 1960, Decimal( '2000' ), 85 ), )
        by_symbol = { term.symbol: term.value for term in methodology( solo, ( 70, ) ) }
        self.assertTrue( by_symbol[ 'R' ].startswith( '+' ) )      # delaying to 70 adds delayed credits


def _couple_form_data() -> dict:
    return { 'household' : 'couple',
             's0_birth_year' : '1960', 's0_pia' : '3000', 's0_life' : '84',
             's1_birth_year' : '1962', 's1_pia' : '1200', 's1_life' : '88',
             'cola' : '2.5', 'inflation' : '2.5', 'benefits_payable' : '100', 'reduction_year' : '2033' }


@override_settings( SUPPRESS_AUTHENTICATION = False )
class MethodologyModalTest( TestCase ):

    def setUp( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _couple_form_data() )

    def test_an_anonymous_visitor_can_open_the_methodology( self ):
        response = self.client.get(
            reverse( 'calculators:ss_timing:methodology', args = [ '67-67' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        self.assertEqual( response.status_code, 200 )
        modal = json.loads( response.content )[ 'modal' ]
        self.assertIn( 'How this is calculated', modal )
        self.assertIn( 'PIA', modal )

    def test_a_bad_combo_is_not_found( self ):
        self.assertEqual( self.client.get(
            reverse( 'calculators:ss_timing:methodology', args = [ '80-80' ] ) ).status_code, 404 )
