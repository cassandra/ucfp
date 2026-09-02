"""The profile-freshness gate: an outdated profile (one predating the current month) steers the user to an
explicit review/advance before they edit it or run against it.

`profile_refresh_required` is the shared signal. The forecast hub and a profile interview section redirect
to the Profile page; the Profile page shows the review prompt whose POST advances the snapshot; the
Scenarios/Plans/Assumptions surfaces carry an advisory banner (tested via `profile_refresh_required` here,
rendered by their templates). A read-only viewer and the read-only example org are carved out.
"""
from datetime import date, datetime, timezone as datetime_timezone
from types import SimpleNamespace

import time_machine
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from organization.models import Organization

from ucfp.inputs.interview import SUBJECTS_STEP, applicable_sections, flow_of
from ucfp.inputs.mixins import profile_refresh_required
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.repository import (
    current_effective_date, latest_profile, save_profile, store_profile )
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.views import FlowEntryView, InterviewView
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.onboarding.constants import EXAMPLE_ORGANIZATION_UUID
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.views import FinancialForecastView
from ucfp.session_state import SessionState

User = get_user_model()


def _profile() -> Profile:
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _profile_section_keys( profile ) -> list:
    return [ section.key for section in applicable_sections( profile )
             if flow_of( section ) == 'profile' and section.form is not None ]


def _outdated_record( organization, *, acknowledged = None ) -> ProfileRecord:
    """A prior-month profile record. Complete as of its own month by default (every profile section
    reviewed); pass `acknowledged` for an in-progress one."""
    profile = _profile()
    record  = ProfileRecord(
        organization = organization, effective_date = date( 2020, 1, 1 ), label = 'January 2020',
        acknowledged_sections = _profile_section_keys( profile ) if acknowledged is None else acknowledged )
    store_profile( record, profile )
    record.save()
    return record


def _request( factory_call, organization, *, can_write = True ):
    request = factory_call
    request.organization           = organization
    request.organization_can_write = can_write
    request.session_state          = SessionState()
    request.session                = dict()
    return request


class ProfileRefreshRequiredTests( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Gate' )

    def _req( self, organization, can_write = True ):
        return SimpleNamespace( organization = organization, organization_can_write = can_write )

    def test_an_outdated_profile_requires_refresh( self ):
        _outdated_record( self.org )
        self.assertTrue( profile_refresh_required( self._req( self.org ) ) )

    def test_a_current_month_profile_does_not( self ):
        save_profile( self.org, _profile() )                 # writes the current month
        self.assertFalse( profile_refresh_required( self._req( self.org ) ) )

    def test_no_profile_does_not( self ):
        self.assertFalse( profile_refresh_required( self._req( self.org ) ) )

    def test_an_incomplete_profile_is_not_flagged( self ):
        # A still-in-progress profile (only some sections reviewed) is finished in place, not advanced --
        # even when it predates the current month. It has no snapshot to protect, so it is never gated.
        _outdated_record( self.org, acknowledged = [ SUBJECTS_STEP ] )
        self.assertFalse( profile_refresh_required( self._req( self.org ) ) )

    def test_a_read_only_viewer_is_carved_out( self ):
        _outdated_record( self.org )
        self.assertFalse( profile_refresh_required( self._req( self.org, can_write = False ) ) )

    def test_a_request_without_an_organization_is_safe( self ):
        self.assertFalse( profile_refresh_required( SimpleNamespace() ) )

    def test_the_read_only_example_org_is_carved_out( self ):
        # The example org's aged sample data is not the user's to refresh, so it is never gated.
        example = Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = 'Example' )
        _outdated_record( example )
        self.assertFalse( profile_refresh_required( self._req( example ) ) )


class ProfilePagePromptTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()    # the current-profile path builds the Default scenario's assumptions
        self.org     = Organization.objects.create( name = 'Prompt' )
        self.factory = RequestFactory()

    def _view( self ):
        view = FlowEntryView()
        view.flow = 'profile'
        return view

    def test_outdated_profile_shows_the_review_prompt( self ):
        _outdated_record( self.org )
        response = self._view().get( _request( self.factory.get( '/inputs/profile/' ), self.org ) )
        self.assertEqual( response.status_code, 200 )        # the prompt page, not a redirect into the editor
        self.assertIn( b'Review', response.content )

    def test_a_current_profile_enters_the_editor( self ):
        save_profile( self.org, _profile() )
        response = self._view().get( _request( self.factory.get( '/inputs/profile/' ), self.org ) )
        self.assertEqual( response.status_code, 302 )
        self.assertIn( '/interview/', response.url )

    def test_acknowledging_advances_the_snapshot_and_returns_to_the_profile( self ):
        _outdated_record( self.org )
        response = self._view().post( _request( self.factory.post( '/inputs/profile/' ), self.org ) )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response.url, '/inputs/profile/' )
        advanced = latest_profile( self.org )
        self.assertEqual( advanced.effective_date, current_effective_date() )
        self.assertEqual( advanced.acknowledged_section_keys, { SUBJECTS_STEP } )   # volatile sections reopened
        # The prior month is retained as history.
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 2 )

    def test_a_post_does_not_advance_an_incomplete_profile( self ):
        # A crafted POST cannot copy an in-progress profile forward: only a complete, outdated one advances.
        prior = _outdated_record( self.org, acknowledged = [ SUBJECTS_STEP ] )
        response = self._view().post( _request( self.factory.post( '/inputs/profile/' ), self.org ) )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 1 )   # no copy
        self.assertEqual( latest_profile( self.org ).pk, prior.pk )


class HubAndInterviewGateTests( TestCase ):

    def setUp( self ):
        self.org     = Organization.objects.create( name = 'HubGate' )
        self.factory = RequestFactory()

    def test_the_forecast_hub_redirects_an_outdated_profile_to_review( self ):
        _outdated_record( self.org )
        response = FinancialForecastView().get(
            _request( self.factory.get( '/plan/financial-forecast/' ), self.org ) )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response.url, '/inputs/profile/' )

    def test_the_forecast_hub_post_refuses_to_run_an_outdated_profile( self ):
        # The run path is separate from GET and safety-critical: it must not project a stale snapshot.
        _outdated_record( self.org )
        response = FinancialForecastView().post(
            _request( self.factory.post( '/plan/financial-forecast/' ), self.org ) )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response.url, '/inputs/profile/' )

    def test_a_profile_section_of_a_complete_outdated_profile_redirects_to_review( self ):
        # A profile section of a complete, outdated snapshot short-circuits to the review prompt *before*
        # any seeding/acknowledgment, so the immutable prior month is never touched (no side-effect mint).
        prior = _outdated_record( self.org )                 # complete as of January 2020

        response = InterviewView().get(
            _request( self.factory.get( '/inputs/interview/accounts/' ), self.org ), 'accounts' )

        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response.url, '/inputs/profile/' )
        prior.refresh_from_db()
        self.assertEqual( prior.acknowledged_section_keys, set( _profile_section_keys( _profile() ) ) )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 1 )


class CurrentEffectiveDateBoundaryTests( TestCase ):
    """Regression for #246: the canonical effective month is computed in UTC, so it is the same value
    whether or not a request has activated a local timezone. Before the fix, `localdate()` read the
    *active* zone, so a profile stamped inside a request during the local/UTC month-boundary window
    disagreed with the month the rest of the app compared it against outside one."""

    # 03:00 UTC on the 1st is still late on the previous evening -- and the previous month -- across the
    # Americas, so the active zone and UTC sit in different calendar months.
    BOUNDARY_INSTANT = datetime( 2026, 9, 1, 3, 0, tzinfo = datetime_timezone.utc )

    def test_the_effective_month_is_the_utc_month_regardless_of_active_timezone( self ):
        with time_machine.travel( self.BOUNDARY_INSTANT ):
            with timezone.override( 'America/Chicago' ):   # still 2026-08-31 locally
                self.assertEqual( timezone.localdate(), date( 2026, 8, 31 ) )
                self.assertEqual( current_effective_date(), date( 2026, 9, 1 ) )
            # Outside any activated zone (the settings UTC default) the value is unchanged: inside == outside.
            self.assertEqual( current_effective_date(), date( 2026, 9, 1 ) )


class FreshnessGateThroughTheStackTests( TestCase ):
    """End-to-end through the real request stack (auth + `ensure_organization` + routing), which the
    direct-method tests above bypass: an owner whose only profile predates the current month is steered
    through the review before the hub will run, and the prompt's POST advances the snapshot."""

    def setUp( self ):
        self.user = User.objects.create_user( email = 'owner@x.test' )
        self.org  = Organization.objects.create_for_owner( self.user, 'Mine' )
        _outdated_record( self.org )
        self.client.force_login( self.user )

    def test_the_hub_redirects_to_the_profile_review( self ):
        response = self.client.get( reverse( 'financial_forecast' ) )
        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )

    def test_the_profile_page_shows_the_prompt_and_its_post_advances( self ):
        prompt = self.client.get( reverse( 'flow_profile' ) )
        self.assertEqual( prompt.status_code, 200 )
        self.assertTemplateUsed( prompt, 'inputs/profile_refresh.html' )

        acknowledged = self.client.post( reverse( 'flow_profile' ) )
        self.assertRedirects( acknowledged, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( latest_profile( self.org ).effective_date, current_effective_date() )

    def test_the_scenarios_page_shows_the_advisory_banner( self ):
        response = self.client.get( reverse( 'scenarios_home' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertTrue( response.context[ 'profile_refresh_required' ] )
        self.assertContains( response, 'Your profile is from' )
        # The advisory carries a right-aligned accent CTA to the review, not just an inline mention.
        self.assertContains( response, 'btn-cta' )
        self.assertContains( response, 'Review profile' )
