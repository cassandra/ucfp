"""The login-free benefit estimator: the modal seeds and recomputes the estimate through the jurisdiction
facade, the confirm writes it back into the calculator's PIA field, and the whole flow is reachable
anonymously. The estimate math itself is the jurisdiction facade's (tested there); here we cover the glue.
"""
import json
import re

from decimal import Decimal

from django.http import Http404, QueryDict
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ucfp.calculators.ss_timing.views import BenefitEstimateApplyView, BenefitEstimatorModalView
from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.session_state import SessionState

_ESTIMATOR = GovernmentPension( JurisdictionType.US_FEDERAL )


def _input_value( html, field_name ):
    """The (comma-stripped) value attribute of the named input in a rendered fragment, as a Decimal."""
    match = re.search( rf'name="{field_name}"[^>]*\bvalue="([^"]*)"', html ) \
        or re.search( rf'\bvalue="([^"]*)"[^>]*name="{field_name}"', html )
    return Decimal( match.group( 1 ).replace( ',', '' ) ) if match and match.group( 1 ) else None


class EstimatorModalViewTest( TestCase ):

    def _request( self, method, data = None ):
        request = getattr( RequestFactory(), method )(
            '/x/', data, HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def test_get_opens_the_modal_with_the_income_field( self ):
        response = BenefitEstimatorModalView().get( self._request( 'get' ), index = 0 )
        html = json.loads( response.content )[ 'modal' ]
        self.assertIn( 'Average annual income', html )
        self.assertIn( 'name="income"', html )

    def test_post_recomputes_the_benefit_through_the_facade( self ):
        data = QueryDict( mutable = True )
        data[ 'income' ] = '80,000'
        response = BenefitEstimatorModalView().post( self._request( 'post', data ), index = 0 )
        fragment = json.loads( response.content )[ 'replace' ][ 'benefit-estimate' ]
        self.assertEqual(
            _input_value( fragment, 'benefit' ), _ESTIMATOR.estimate_entitlement( Decimal( '80000' ) ) )

    def test_an_out_of_range_person_index_is_not_found( self ):
        with self.assertRaises( Http404 ):
            BenefitEstimatorModalView().get( self._request( 'get' ), index = 2 )


class EstimateApplyViewTest( TestCase ):

    def _post( self, index, benefit ):
        data = QueryDict( mutable = True )
        data[ 'benefit' ] = benefit
        request = RequestFactory().post( '/x/', data, HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.session_state = SessionState()
        request.session       = dict()
        return BenefitEstimateApplyView().post( request, index = index )

    def test_confirm_writes_the_benefit_into_the_persons_pia_field( self ):
        response = self._post( 0, '3200' )
        content  = json.loads( response.content )[ 'replace' ][ 'pia-input-0' ]
        self.assertIn( 'name="s0_pia"', content )
        self.assertEqual( _input_value( content, 's0_pia' ), Decimal( '3200' ) )

    def test_confirm_targets_the_partner_field_for_index_one( self ):
        response = self._post( 1, '1500' )
        self.assertIn( 'pia-input-1', json.loads( response.content )[ 'replace' ] )
        self.assertIn( 'name="s1_pia"', json.loads( response.content )[ 'replace' ][ 'pia-input-1' ] )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class EstimatorReachabilityTest( TestCase ):

    def test_an_anonymous_visitor_can_open_the_estimator( self ):
        response = self.client.get(
            reverse( 'calculators:ss_timing:estimate', args = [ 0 ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        self.assertEqual( response.status_code, 200 )
        self.assertIn( 'modal', json.loads( response.content ) )
