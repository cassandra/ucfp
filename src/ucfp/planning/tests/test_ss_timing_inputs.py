"""The login-free Social Security claiming calculator: the input form's validation and value<->domain
mapping, and the public inputs/results views (anonymous access, session persistence, the prefill round
trip). The signed-in Profile/scenario prefill and the #235 estimator arrive in later phases.
"""
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.planning.ss_timing import Assumptions
from ucfp.planning.ss_timing_forms import (
    HOUSEHOLD_COUPLE, HOUSEHOLD_SINGLE, SocialSecurityTimingForm,
    claimants_and_assumptions, default_inputs )
from ucfp.session_state import SessionState

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore

_ASSUMPTIONS = { 'cola' : '2.5', 'discount' : '2.5', 'benefits_payable' : '100' }


def _single_data( ** overrides ) -> dict:
    data = { 'household' : HOUSEHOLD_SINGLE, 's0_birth_year' : '1960', 's0_pia' : '2000',
             's0_life' : '85', ** _ASSUMPTIONS }
    data.update( overrides )
    return data


def _couple_data( ** overrides ) -> dict:
    data = _single_data( household = HOUSEHOLD_COUPLE,
                         s1_birth_year = '1962', s1_pia = '1200', s1_life = '90' )
    data.update( overrides )
    return data


class FormValidationTest( SimpleTestCase ):

    def test_a_couple_requires_the_partner_fields( self ):
        form = SocialSecurityTimingForm(
            data = _couple_data( s1_birth_year = '', s1_pia = '', s1_life = '' ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( 's1_pia', form.errors )

    def test_a_single_household_ignores_the_blank_partner_fields( self ):
        form = SocialSecurityTimingForm( data = _single_data() )
        self.assertTrue( form.is_valid(), form.errors )
        self.assertNotIn( 's1_pia', form.cleaned_inputs() )

    def test_a_future_birth_year_is_rejected( self ):
        form = SocialSecurityTimingForm( data = _single_data( s0_birth_year = '3000' ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( 's0_birth_year', form.errors )


class FormMappingTest( SimpleTestCase ):

    def test_cleaned_inputs_map_to_two_claimants_and_the_assumptions( self ):
        form = SocialSecurityTimingForm( data = _couple_data() )
        self.assertTrue( form.is_valid(), form.errors )
        claimants, assumptions = claimants_and_assumptions( form.cleaned_inputs() )
        self.assertEqual( [ c.name for c in claimants ], [ 'You', 'Spouse or partner' ] )
        self.assertEqual( claimants[ 0 ].birth_year, 1960 )
        self.assertEqual( claimants[ 1 ].pia_monthly, Decimal( '1200' ) )
        self.assertEqual( claimants[ 1 ].expected_lifetime, 90 )
        self.assertEqual( assumptions.cola, Rate( Decimal( '0.025' ) ) )
        self.assertEqual( assumptions.inflation, Rate( Decimal( '0.025' ) ) )       # the discount percent
        self.assertEqual( assumptions.benefits_payable, Rate( Decimal( '1' ) ) )    # 100%

    def test_a_single_household_maps_to_one_claimant( self ):
        form = SocialSecurityTimingForm( data = _single_data() )
        self.assertTrue( form.is_valid(), form.errors )
        claimants, _assumptions = claimants_and_assumptions( form.cleaned_inputs() )
        self.assertEqual( len( claimants ), 1 )

    def test_default_inputs_seed_the_assumption_percents( self ):
        seeded = default_inputs( Assumptions(
            inflation = Rate( Decimal( '0.03' ) ), cola = Rate( Decimal( '0.02' ) ) ) )
        self.assertEqual( seeded[ 'household' ], HOUSEHOLD_COUPLE )
        self.assertEqual( seeded[ 'discount' ], '3' )                # 0.03 -> '3'
        self.assertEqual( seeded[ 'cola' ], '2' )
        self.assertNotIn( 's0_birth_year', seeded )                  # people are left blank


class SessionRoundTripTest( SimpleTestCase ):

    def test_ss_timing_inputs_survive_a_session_round_trip( self ):
        request = RequestFactory().get( '/' )
        request.session = _SessionStore()
        state = SessionState.from_session( request )
        state.ss_timing_inputs = { 'household' : HOUSEHOLD_SINGLE, 's0_birth_year' : 1960 }
        state.to_session( request )
        restored = SessionState.from_session( request )
        self.assertEqual(
            restored.ss_timing_inputs, { 'household' : HOUSEHOLD_SINGLE, 's0_birth_year' : 1960 } )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class InputsViewTest( TestCase ):

    def test_an_anonymous_visitor_can_open_the_form( self ):
        # The route is in the auth middleware's exempt set, so an anonymous GET reaches the view (200)
        # rather than being redirected to sign in. The default assumptions are stubbed to avoid the
        # seeded-parameter-set DB read (seeding is a deploy step, not a test fixture).
        with patch( 'ucfp.planning.ss_timing_prefill.default_economics',
                    return_value = EconomicParameters( inflation = Rate( Decimal( '0.025' ) ),
                                                       social_security_cola = Rate( Decimal( '0.025' ) ) ) ):
            response = self.client.get( reverse( 'ss_timing' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Compare claiming ages' )

    def test_a_valid_submission_persists_and_redirects_to_the_results( self ):
        response = self.client.post( reverse( 'ss_timing' ), _single_data() )
        self.assertRedirects( response, reverse( 'ss_timing_results' ) )

    def test_an_invalid_submission_rerenders_the_form_with_errors( self ):
        response = self.client.post( reverse( 'ss_timing' ), _single_data( s0_pia = '' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'is required', status_code = 200 )

    def test_a_submission_is_remembered_and_prefills_the_returning_form( self ):
        self.client.post( reverse( 'ss_timing' ), _single_data() )
        response = self.client.get( reverse( 'ss_timing' ) )
        self.assertContains( response, 'prefilled your last entries' )
        self.assertContains( response, 'value="1960"' )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ResultsViewTest( TestCase ):

    def test_results_without_stored_inputs_redirect_to_the_form( self ):
        # Do not fetch the target: the empty-session form GET reads the seeded default preset, absent in
        # the test DB (a deploy-seeded parameter set). The rendering path is covered with it stubbed above.
        self.assertRedirects(
            self.client.get( reverse( 'ss_timing_results' ) ), reverse( 'ss_timing' ),
            fetch_redirect_response = False )

    def test_results_rank_the_strategies_after_a_submission( self ):
        self.client.post( reverse( 'ss_timing' ), _single_data() )
        response = self.client.get( reverse( 'ss_timing_results' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Best strategy' )
