"""The signed-in prefill for the Social Security claiming calculator: people from the Profile (birth year
and PIA, never the expected lifetime), assumptions from the current/most-recent scenario or the system
defaults, the precedence of a remembered session entry, and that the form never writes back to the Profile.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from common.rate import Rate
from organization.models import Organization

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions as InputAssumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import latest_profile, load_profile, save_profile
from ucfp.inputs.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, GovernmentPensionEntitlement, Profile, SubjectProfile )
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.calculators.ss_timing.prefill import build_prefill
from ucfp.session_state import SessionState

_DEFAULT_ECONOMICS = 'ucfp.calculators.ss_timing.prefill.default_economics'


def _couple_profile() -> Profile:
    return Profile(
        subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1960, 1, 1 ) ),
                     SubjectProfile( PARTNER_SUBJECT_HANDLE, 'Bob', date( 1962, 1, 1 ) ) ],
        government_pension = [
            GovernmentPensionEntitlement( PRIMARY_SUBJECT_HANDLE, Decimal( '3000' ) ),
            GovernmentPensionEntitlement( PARTNER_SUBJECT_HANDLE, Decimal( '1200' ) ) ] )


class PrefillPeopleTest( TestCase ):
    """`build_prefill` unit-level: the people mapping from a Profile, exercised directly with a request
    whose default assumptions are stubbed (the seeded preset is a deploy step, absent in the test DB)."""

    def setUp( self ):
        self.user         = get_user_model().objects.create_user( email = 'a@x.test' )
        self.organization = Organization.objects.create_default_for_user( self.user )

    def _request( self, user ):
        request = RequestFactory().get( '/' )
        request.user          = user
        request.session       = dict()
        request.session_state = SessionState()
        return request

    def _build( self, user ):
        with patch( _DEFAULT_ECONOMICS, return_value = EconomicParameters() ):
            return build_prefill( self._request( user ) )

    def test_a_couple_profile_prefills_birth_years_and_pias_but_not_lifetimes( self ):
        save_profile( self.organization, _couple_profile() )
        prefill = self._build( self.user )
        self.assertTrue( prefill.from_profile )
        self.assertEqual( prefill.initial[ 'household' ], 'couple' )
        self.assertEqual( prefill.initial[ 's0_birth_year' ], 1960 )
        self.assertEqual( prefill.initial[ 's0_pia' ], '3000' )
        self.assertEqual( prefill.initial[ 's1_birth_year' ], 1962 )
        self.assertEqual( prefill.initial[ 's1_pia' ], '1200' )
        self.assertNotIn( 's0_life', prefill.initial )                 # expected lifetime is never prefilled
        self.assertNotIn( 's1_life', prefill.initial )

    def test_a_single_subject_profile_prefills_a_single_household( self ):
        save_profile( self.organization, Profile(
            subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1960, 1, 1 ) ) ],
            government_pension = [
                GovernmentPensionEntitlement( PRIMARY_SUBJECT_HANDLE, Decimal( '2000' ) ) ] ) )
        prefill = self._build( self.user )
        self.assertEqual( prefill.initial[ 'household' ], 'single' )
        self.assertEqual( prefill.initial[ 's0_pia' ], '2000' )

    def test_a_subject_without_an_entitlement_prefills_no_pia( self ):
        save_profile( self.organization, Profile(
            subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1960, 1, 1 ) ) ] ) )
        prefill = self._build( self.user )
        self.assertEqual( prefill.initial[ 's0_birth_year' ], 1960 )
        self.assertNotIn( 's0_pia', prefill.initial )

    def test_an_anonymous_visitor_gets_blank_people_and_the_default_source( self ):
        prefill = self._build( AnonymousUser() )
        self.assertFalse( prefill.from_profile )
        self.assertEqual( prefill.assumptions_source, 'system defaults' )
        self.assertNotIn( 's0_birth_year', prefill.initial )


class PrefillAssumptionsTest( TestCase ):
    """Where the assumptions are drawn from: the most recent saved scenario's economics, labelled by its
    name; the system defaults otherwise."""

    def setUp( self ):
        self.user         = get_user_model().objects.create_user( email = 'a@x.test' )
        self.organization = Organization.objects.create_default_for_user( self.user )
        save_profile( self.organization, _couple_profile() )

    def _request( self ):
        request = RequestFactory().get( '/' )
        request.user          = self.user
        request.session       = dict()
        request.session_state = SessionState()
        return request

    def _save_scenario( self, label, economics ):
        plans = PlansRecord( organization = self.organization, label = f'{label} Plans' )
        save_plans( plans, Plans() )
        assumptions = AssumptionsRecord( organization = self.organization, label = f'{label} Assumptions' )
        save_assumptions( assumptions, InputAssumptions( economics = economics ) )
        return create_scenario( self.organization, plans, assumptions, label = label )

    def test_assumptions_come_from_the_most_recent_scenario( self ):
        self._save_scenario( 'Baseline', EconomicParameters(
            inflation = Rate( Decimal( '0.02' ) ), social_security_cola = Rate( Decimal( '0.04' ) ) ) )
        prefill = build_prefill( self._request() )
        self.assertEqual( prefill.assumptions_source, 'your scenario “Baseline”' )
        self.assertEqual( prefill.initial[ 'cola' ], '4' )            # 0.04 -> '4'
        self.assertEqual( prefill.initial[ 'discount' ], '2' )        # inflation -> the discount

    def test_falls_back_to_the_system_defaults_without_a_scenario( self ):
        with patch( _DEFAULT_ECONOMICS, return_value = EconomicParameters(
                social_security_cola = Rate( Decimal( '0.025' ) ) ) ):
            prefill = build_prefill( self._request() )
        self.assertEqual( prefill.assumptions_source, 'system defaults' )
        self.assertEqual( prefill.initial[ 'cola' ], '2.5' )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class PrefillThroughTheViewTest( TestCase ):

    def setUp( self ):
        self.user         = get_user_model().objects.create_user( email = 'a@x.test' )
        self.organization = Organization.objects.create_default_for_user( self.user )
        save_profile( self.organization, _couple_profile() )
        self.client.force_login( self.user )

    def test_the_signed_in_form_renders_prefilled_from_the_profile( self ):
        with patch( _DEFAULT_ECONOMICS, return_value = EconomicParameters() ):
            response = self.client.get( reverse( 'calculators:ss_timing:inputs' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Prefilled from your profile' )
        self.assertContains( response, 'value="1960"' )
        self.assertContains( response, 'value="3000"' )

    def test_a_remembered_session_entry_wins_over_the_profile( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), {
            'household' : 'single', 's0_birth_year' : '1955', 's0_pia' : '900', 's0_life' : '85',
            'cola' : '2.5', 'discount' : '2.5', 'benefits_payable' : '100' } )
        response = self.client.get( reverse( 'calculators:ss_timing:inputs' ) )
        self.assertContains( response, 'value="1955"' )              # the remembered entry
        self.assertNotContains( response, 'value="1960"' )           # not the profile
        self.assertNotContains( response, 'Prefilled from your profile' )

    def test_submitting_does_not_change_the_saved_profile( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), {
            'household' : 'couple',
            's0_birth_year' : '1900', 's0_pia' : '1', 's0_life' : '70',
            's1_birth_year' : '1901', 's1_pia' : '2', 's1_life' : '71',
            'cola' : '9', 'discount' : '9', 'benefits_payable' : '50' } )
        profile = load_profile( latest_profile( self.organization ) )
        self.assertEqual( profile.subjects[ 0 ].birthdate, date( 1960, 1, 1 ) )
        self.assertEqual( profile.government_pension[ 0 ].monthly_at_normal_age, Decimal( '3000' ) )
