"""The login-free Social Security claiming calculator: the input form's validation and value<->domain
mapping, and the public inputs/results views (anonymous access, session persistence, the prefill round
trip). The signed-in Profile/scenario prefill and the #235 estimator arrive in later phases.
"""
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from organization.models import Organization

from common.rate import Rate
from ucfp.calculators.ss_timing.compute import Assumptions
from ucfp.calculators.ss_timing.forms import (
    HOUSEHOLD_COUPLE, HOUSEHOLD_SINGLE, InputsForm,
    claimants_and_assumptions, default_inputs )
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.session_facts import PersonFacts, SessionFacts
from ucfp.session_state import SessionState

User = get_user_model()

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore

_STUB_ECONOMICS = EconomicParameters( inflation = Rate( Decimal( '0.025' ) ),
                                      social_security_cola = Rate( Decimal( '0.025' ) ) )

_ASSUMPTIONS = { 'inflation' : '2.5', 'benefits_payable' : '100', 'reduction_year' : '2033' }


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
        form = InputsForm(
            data = _couple_data( s1_birth_year = '', s1_pia = '', s1_life = '' ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( 's1_pia', form.errors )

    def test_a_single_household_ignores_the_blank_partner_fields( self ):
        form = InputsForm( data = _single_data() )
        self.assertTrue( form.is_valid(), form.errors )
        self.assertEqual( len( form.session_facts().people ), 1 )     # no partner captured

    def test_a_future_birth_year_is_rejected( self ):
        form = InputsForm( data = _single_data( s0_birth_year = '3000' ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( 's0_birth_year', form.errors )


class FormMappingTest( SimpleTestCase ):

    def test_the_form_maps_to_two_claimants_and_the_assumptions( self ):
        form = InputsForm( data = _couple_data() )
        self.assertTrue( form.is_valid(), form.errors )
        claimants, assumptions = claimants_and_assumptions(
            form.session_facts(), form.assumptions_inputs() )
        self.assertEqual( [ c.name for c in claimants ], [ 'Individual', 'Partner' ] )
        self.assertEqual( claimants[ 0 ].birth_year, 1960 )
        self.assertEqual( claimants[ 1 ].pia_monthly, Decimal( '1200' ) )
        self.assertEqual( claimants[ 1 ].expected_lifetime, 90 )
        self.assertEqual( assumptions.cola, Rate( Decimal( '0.022' ) ) )     # inflation less the 0.3% lag
        self.assertEqual( assumptions.inflation, Rate( Decimal( '0.025' ) ) )       # the discount percent
        self.assertEqual( assumptions.benefits_payable, Rate( Decimal( '1' ) ) )    # 100%

    def test_a_single_household_maps_to_one_claimant( self ):
        form = InputsForm( data = _single_data() )
        self.assertTrue( form.is_valid(), form.errors )
        claimants, _assumptions = claimants_and_assumptions(
            form.session_facts(), form.assumptions_inputs() )
        self.assertEqual( len( claimants ), 1 )

    def test_default_inputs_seed_the_assumption_percents( self ):
        seeded = default_inputs( Assumptions(
            inflation = Rate( Decimal( '0.03' ) ), cola = Rate( Decimal( '0.02' ) ) ) )
        self.assertEqual( seeded[ 'household' ], HOUSEHOLD_COUPLE )
        self.assertEqual( seeded[ 'inflation' ], '3' )               # 0.03 -> '3'
        self.assertNotIn( 'cola', seeded )                           # COLA is derived, not an input
        self.assertNotIn( 's0_birth_year', seeded )                  # people are left blank


class SessionRoundTripTest( SimpleTestCase ):

    def test_session_facts_and_assumptions_survive_a_session_round_trip( self ):
        request = RequestFactory().get( '/' )
        request.session = _SessionStore()
        state = SessionState.from_session( request )
        state.session_facts = SessionFacts( people = [ PersonFacts(
            birth_year = 1960, government_pension_monthly = Decimal( '2000' ), life_expectancy = 85 ) ] )
        state.ss_timing_assumptions = dict( _ASSUMPTIONS )
        state.to_session( request )
        restored = SessionState.from_session( request )
        self.assertFalse( restored.session_facts.is_couple )
        person = restored.session_facts.people[ 0 ]
        self.assertEqual( person.birth_year, 1960 )
        self.assertEqual( person.government_pension_monthly, Decimal( '2000' ) )   # money survives as Decimal
        self.assertEqual( person.life_expectancy, 85 )
        self.assertEqual( restored.ss_timing_assumptions, _ASSUMPTIONS )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class InputsViewTest( TestCase ):

    def test_an_anonymous_visitor_can_open_the_form( self ):
        # The feature's namespace is exempt in the auth middleware, so an anonymous GET reaches the view
        # (200) rather than being redirected to sign in. The default assumptions are stubbed to avoid the
        # seeded-parameter-set DB read (seeding is a deploy step, not a test fixture).
        with patch( 'ucfp.calculators.ss_timing.prefill.default_economics',
                    return_value = _STUB_ECONOMICS ):
            response = self.client.get( reverse( 'calculators:ss_timing:inputs' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Compare claiming ages' )
        self.assertNotContains( response, 'aria-label="breadcrumb"' )    # no app to return to

    def test_a_signed_in_visitor_sees_the_dashboard_breadcrumb( self ):
        user = User.objects.create_user( email = 'owner@x.test', password = 'x' )
        Organization.objects.create_for_owner( user, name = 'Mine' )
        self.client.force_login( user )
        with patch( 'ucfp.calculators.ss_timing.prefill.default_economics',
                    return_value = _STUB_ECONOMICS ):
            response = self.client.get( reverse( 'calculators:ss_timing:inputs' ) )
        self.assertContains( response, 'aria-label="breadcrumb"' )
        self.assertContains( response, reverse( 'dashboard' ) )

    def test_a_valid_submission_persists_and_redirects_to_the_results( self ):
        response = self.client.post( reverse( 'calculators:ss_timing:inputs' ), _single_data() )
        self.assertRedirects( response, reverse( 'calculators:ss_timing:results' ) )

    def test_an_invalid_submission_rerenders_the_form_with_errors( self ):
        response = self.client.post( reverse( 'calculators:ss_timing:inputs' ), _single_data( s0_pia = '' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'is required', status_code = 200 )
        self.assertContains( response, 'Something needs fixing' )        # the top-of-form error summary

    def test_a_submission_is_remembered_and_prefills_the_returning_form( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _single_data() )
        response = self.client.get( reverse( 'calculators:ss_timing:inputs' ) )
        self.assertContains( response, 'value="1960"' )        # the remembered birth year prefills


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ResultsViewTest( TestCase ):

    def test_results_without_stored_inputs_redirect_to_the_form( self ):
        # Do not fetch the target: the empty-session form GET reads the seeded default preset, absent in
        # the test DB (a deploy-seeded parameter set). The rendering path is covered with it stubbed above.
        self.assertRedirects(
            self.client.get( reverse( 'calculators:ss_timing:results' ) ),
            reverse( 'calculators:ss_timing:inputs' ), fetch_redirect_response = False )

    def test_results_render_the_comparison_after_a_submission( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _single_data() )
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Top strategies' )
        self.assertContains( response, 'Lifetime total' )
