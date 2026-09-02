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
    claimants_and_assumptions, default_inputs, is_runnable )
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.session_facts import PersonFacts, SessionFacts
from ucfp.session_state import SessionState

User = get_user_model()

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore

_STUB_ECONOMICS = EconomicParameters( inflation = Rate( Decimal( '0.025' ) ),
                                      social_security_cola = Rate( Decimal( '0.025' ) ) )

_ASSUMPTIONS = { 'inflation' : '2.5', 'expected_return' : '4.5',
                 'benefits_payable' : '100', 'reduction_year' : '2033' }


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

    def test_a_return_below_inflation_is_rejected( self ):
        # A below-inflation return would invert the opportunity-cost framing ("above inflation"), so it is
        # rejected rather than modeled.
        form = InputsForm( data = _single_data( inflation = '3', expected_return = '2' ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( 'expected_return', form.errors )


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
        self.assertEqual( assumptions.inflation, Rate( Decimal( '0.025' ) ) )       # the run's inflation
        self.assertEqual( assumptions.expected_return, Rate( Decimal( '0.045' ) ) )  # 4.5% nominal ...
        self.assertEqual( assumptions.discount_rate, Rate( Decimal( '0.045' ) ) )    # ... = the PV discount
        self.assertEqual( assumptions.benefits_payable, Rate( Decimal( '1' ) ) )    # 100%

    def test_a_session_without_an_expected_return_discounts_at_inflation( self ):
        # A session stored before this feature has no expected_return; it falls back to inflation gracefully
        # rather than erroring, so an old session still renders results.
        facts  = SessionFacts( people = [ PersonFacts( 1960, Decimal( '2000' ), 85 ) ] )
        legacy = { 'inflation' : '2.5', 'benefits_payable' : '100', 'reduction_year' : '2033' }
        _claimants, assumptions = claimants_and_assumptions( facts, legacy )
        self.assertIsNone( assumptions.expected_return )
        self.assertEqual( assumptions.discount_rate, assumptions.inflation )

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
        self.assertEqual( seeded[ 'expected_return' ], '5' )         # inflation 3% + the 2% real default
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

    def test_a_benefit_less_person_round_trips_with_no_benefit( self ):
        # A visitor who enters a birth year but skips the benefit: the None must survive the JSON round
        # trip (the `None if ... else str()` write branch and the None read branch), not become '' or '0'.
        request = RequestFactory().get( '/' )
        request.session = _SessionStore()
        state = SessionState.from_session( request )
        state.session_facts = SessionFacts( people = [ PersonFacts( birth_year = 1959 ) ] )
        state.to_session( request )
        person = SessionState.from_session( request ).session_facts.people[ 0 ]
        self.assertEqual( person.birth_year, 1959 )
        self.assertIsNone( person.government_pension_monthly )
        self.assertIsNone( person.life_expectancy )

    def test_malformed_stored_facts_read_back_as_none_rather_than_raising( self ):
        # The session is JSON-backed and could hold a bad value; from_storage tolerates it (returns None)
        # rather than raising, so a corrupt session never 500s the page.
        facts = SessionFacts.from_storage( { 'people': [
            { 'birth_year': 'nineteen', 'government_pension_monthly': 'lots', 'life_expectancy': None } ] } )
        person = facts.people[ 0 ]
        self.assertIsNone( person.birth_year )
        self.assertIsNone( person.government_pension_monthly )


class RunnableGateTest( SimpleTestCase ):
    """`is_runnable` guards the results views against a partial or oversized household -- `SessionFacts` is
    a neutral, cross-tool bag, so the sweep must not assume the SS form filled every field."""

    def _complete_person( self ) -> PersonFacts:
        return PersonFacts( birth_year = 1960, government_pension_monthly = Decimal( '2000' ),
                            life_expectancy = 85 )

    def test_a_complete_single_household_is_runnable( self ):
        facts = SessionFacts( people = [ self._complete_person() ] )
        self.assertTrue( is_runnable( facts, dict( _ASSUMPTIONS ) ) )

    def test_a_person_missing_a_claiming_fact_is_not_runnable( self ):
        partial = PersonFacts( birth_year = 1960, life_expectancy = 85 )      # no benefit
        self.assertFalse( is_runnable( SessionFacts( people = [ partial ] ), dict( _ASSUMPTIONS ) ) )

    def test_more_than_two_people_is_not_runnable( self ):
        people = [ self._complete_person() for _ in range( 3 ) ]
        self.assertFalse( is_runnable( SessionFacts( people = people ), dict( _ASSUMPTIONS ) ) )

    def test_no_people_or_missing_assumptions_are_not_runnable( self ):
        self.assertFalse( is_runnable( SessionFacts(), dict( _ASSUMPTIONS ) ) )
        self.assertFalse( is_runnable( SessionFacts( people = [ self._complete_person() ] ), {} ) )


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
        self.assertContains( response, 'Expected asset return' )         # the opportunity-cost input ...
        self.assertContains( response, 'value="4.5"' )                   # ... default = inflation + 2% real
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
        self.assertContains( response, 'is-invalid' )                    # the erroring field is highlighted
        self.assertContains( response, 'aria-describedby="id_s0_pia-errors"' )   # wired to its error list

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
