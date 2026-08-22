"""`StartTourView` / `TourProfileView`: "Take a Tour" joins the visitor to the sample org, switches to it,
and lands on the Profile step -- the *real* interview (`InterviewView`) rendered under the tour shell,
not the app nav. An anonymous visitor is minted a Guest first; a signed-in visitor is used as-is (no
conversion, no blocking). Unavailable when the sample org is not seeded."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, tag
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.interview import first_section_of_flow
from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.seeding import _seed_records, seed_sample_org
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets

User = get_user_model()


class StartTourTest( TestCase ):

    def _seed_sample( self ):
        return Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

    def _tour_profile_url( self ):
        return reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } )

    def _current_org_uuid( self ):
        return self.client.session.get( 'current_organization_uuid' )

    def test_anonymous_take_a_tour_mints_a_guest_and_enters( self ):
        sample = self._seed_sample()

        response = self.client.post( reverse( 'start_tour' ) )

        self.assertRedirects( response, self._tour_profile_url(), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )                               # one Guest minted
        member = OrganizationMember.objects.get( organization = sample )          # joined as VIEWER
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )
        self.assertTrue( member.user.is_guest )
        self.assertEqual( self._current_org_uuid(), str( SAMPLE_ORGANIZATION_UUID ) )  # switched to sample

    def test_signed_in_visitor_enters_without_a_new_account( self ):
        sample = self._seed_sample()
        user = User.objects.create_user( email = 'v@x.test' )
        self.client.force_login( user )

        response = self.client.post( reverse( 'start_tour' ) )

        self.assertRedirects( response, self._tour_profile_url(), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )                               # no second account
        member = OrganizationMember.objects.get( organization = sample, user = user )
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )
        self.assertEqual( self._current_org_uuid(), str( SAMPLE_ORGANIZATION_UUID ) )

    def test_tour_profile_renders_the_real_interview_under_the_tour_shell( self ):
        _seed_records( self._seed_sample() )                     # a real Profile (no forecast) to render
        self.client.post( reverse( 'start_tour' ) )              # enter as a VIEWER guest

        response = self.client.get( self._tour_profile_url() )

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'onboarding/tour/interview.html' )     # the tour's own page
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell
        self.assertTemplateUsed( response, 'inputs/interview/body.html' )         # the real interview body
        self.assertTemplateNotUsed( response, 'pages/app_base.html' )             # not the app chrome
        # The interview's navigation is retargeted to the tour route (stepper/Next), so a reload no longer
        # escapes to the real interview page; and a last section has no completion destination -> no Finish.
        self.assertEqual( response.context[ 'section_url_name' ], 'tour_profile' )
        self.assertIsNone( response.context[ 'completion_destination' ] )  # no Finish while browsing

    def test_tour_scenario_shows_plans_and_assumptions_in_scenario_context( self ):
        _seed_records( self._seed_sample() )                     # real Plans/Assumptions + sample scenario
        self.client.post( reverse( 'start_tour' ) )

        url = reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'plans' ).key } )
        response = self.client.get( url )

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'onboarding/tour/interview.html' )
        self.assertTemplateUsed( response, 'pages/tour_base.html' )
        self.assertEqual( response.context[ 'section_url_name' ], 'tour_scenario' )   # nav stays in the tour
        # Scenario context: both Plans and Assumptions in the left rail, not one in isolation.
        self.assertTrue( response.context[ 'rail_scenario_mode' ] )
        self.assertEqual( len( response.context[ 'rail_parts' ] ), 2 )
        self.assertIsNone( response.context[ 'completion_destination' ] )  # no Finish while browsing

    def test_a_scenario_visit_does_not_reveal_a_finish_escape( self ):
        # Visiting the scenario sets editing_scenario; that must not give Profile a completion destination
        # (the app's Scenarios page, via the build/component branch) -- the tour never has one.
        _seed_records( self._seed_sample() )
        self.client.post( reverse( 'start_tour' ) )
        self.client.get(                                         # sets editing_scenario in the session
            reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'assumptions' ).key } ) )

        response = self.client.get(
            reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } ) )

        self.assertIsNone( response.context[ 'completion_destination' ] )  # not the app's Scenarios page

    def test_tour_forecast_is_unavailable_without_a_captured_run( self ):
        _seed_records( self._seed_sample() )                     # records but no forecast run
        self.client.post( reverse( 'start_tour' ) )

        response = self.client.get( reverse( 'tour_forecast' ) )

        self.assertEqual( 404, response.status_code )            # DataNotAvailableError, not the run page

    def test_unseeded_sample_makes_the_tour_unavailable( self ):
        response = self.client.post( reverse( 'start_tour' ) )

        self.assertEqual( 404, response.status_code )                             # DataNotAvailableError
        self.assertFalse( User.objects.exists() )                                 # no orphan Guest minted


@tag( 'e2e' )
class TourForecastRenderTest( TestCase ):
    """The Forecast step renders the sample org's captured run under the tour shell -- needs a real
    captured run (seed_sample_org runs a forecast), so it is e2e."""

    def setUp( self ):
        seed_default_parameter_sets()
        User.objects.create_superuser( email = 'admin@x.test', password = 'x' )
        seed_sample_org()                                        # sample org + a captured forecast run

    def test_tour_forecast_renders_the_sample_run_under_the_tour_shell( self ):
        self.client.post( reverse( 'start_tour' ) )              # enter as a VIEWER guest

        response = self.client.get( reverse( 'tour_forecast' ) )

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'onboarding/tour/forecast.html' )
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell
        self.assertTemplateUsed( response, 'planning/pages/run_table_panel.html' )  # summary + table
        self.assertTemplateUsed( response, 'planning/pages/run_books_table.html' )  # the real books table
        self.assertTemplateNotUsed( response, 'pages/app_base.html' )             # not the app chrome


class AddMyDataTest( TestCase ):
    """`AddMyDataView`: the universal graduation -- mint a Guest if anonymous, then ensure an organization
    of the user's own (not the sample) and land on the Profile to start entering data."""

    def _own_org( self, user ):
        return OrganizationMember.objects.get(
            user = user, organization_role = OrganizationRole.OWNER ).organization

    def test_anonymous_add_my_data_mints_a_guest_in_their_own_org( self ):
        response = self.client.post( reverse( 'add_my_data' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )
        own = self._own_org( User.objects.get() )
        self.assertNotEqual( str( own.uuid ), str( SAMPLE_ORGANIZATION_UUID ) )   # their own, not the sample
        self.assertEqual( self.client.session.get( 'current_organization_uuid' ), str( own.uuid ) )

    def test_get_is_rejected_and_mints_no_account( self ):
        # POST-only (inherited from ConvertToGuestView): a crawled GET must never mint a Guest.
        response = self.client.get( reverse( 'add_my_data' ) )

        self.assertEqual( 405, response.status_code )
        self.assertEqual( 0, User.objects.count() )

    def test_existing_owner_switches_without_creating_a_second_org( self ):
        # The reuse branch of ensure_own_organization: an owner keeps their org (no duplicate).
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.post( reverse( 'add_my_data' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( 1, Organization.objects.count() )      # reused, not duplicated
        self.assertEqual( self.client.session.get( 'current_organization_uuid' ), str( own.uuid ) )

    def test_tour_guest_add_my_data_switches_off_the_sample( self ):
        sample = Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # guest, VIEWER of sample, current-org=sample

        response = self.client.post( reverse( 'add_my_data' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )              # no second account
        user = User.objects.get()
        own = self._own_org( user )                             # a fresh owned org, not the sample
        self.assertNotEqual( str( own.uuid ), str( SAMPLE_ORGANIZATION_UUID ) )
        self.assertEqual( self.client.session.get( 'current_organization_uuid' ), str( own.uuid ) )
        # still a member of the sample -- reachable again via the switcher, just no longer the current org
        self.assertTrue( OrganizationMember.objects.filter( user = user, organization = sample ).exists() )


class FeaturePageAddMyDataTest( TestCase ):
    """The real feature pages (here the Profile interview under the app chrome) promote "Add my data" to a
    user whose only org is the read-only sample, and suppress the guest "save your work" email banner there
    -- there is nothing of *theirs* to save yet. Once they own an org, neither prompt shows."""

    _CTA_COPY   = "add your own to build your real plan"
    _EMAIL_COPY = "add an email so you don't lose it"

    def _profile_url( self ):
        return reverse( 'interview_section',
                        kwargs = { 'section': first_section_of_flow( 'profile' ).key } )

    def test_sample_only_user_sees_add_my_data_and_not_the_email_banner( self ):
        _seed_records( Organization.objects.create(               # a complete sample Profile to render
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME ) )
        self.client.post( reverse( 'start_tour' ) )              # guest VIEWER, current-org = sample

        response = self.client.get( self._profile_url() )        # the REAL interview, app chrome

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'pages/app_base.html' )        # not the tour shell
        self.assertTrue( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, self._CTA_COPY )                   # the "Add my data" prompt
        self.assertNotContains( response, self._EMAIL_COPY )              # email pitch stands down

    def test_forecast_hub_promotes_add_my_data_to_a_sample_only_user( self ):
        _seed_records( Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME ) )
        self.client.post( reverse( 'start_tour' ) )              # guest VIEWER, current-org = sample

        response = self.client.get( reverse( 'financial_forecast' ) )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, self._CTA_COPY )

    def test_owner_sees_neither_prompt( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        _seed_records( Organization.objects.create_for_owner( user, 'Mine' ) )   # a profile to render
        self.client.force_login( user )

        response = self.client.get( self._profile_url() )

        self.assertEqual( response.status_code, 200 )
        self.assertFalse( response.context[ 'offer_add_my_data' ] )
        self.assertNotContains( response, self._CTA_COPY )


class ExplainGatingTest( TestCase ):
    """`ExplainView` exposes the two deployment-mode flags its template gates cloud-only chrome on:
    `tour_available` (is the sample org seeded, so "Take a tour" can run) and `authentication_enabled`
    (is sign-in in play, so the "free, no sign-up" reassurance applies). This tests that contract, not
    the page's evolving layout/copy."""

    def test_tour_available_reflects_a_seeded_sample_org( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertFalse( response.context[ 'tour_available' ] )          # no sample seeded -> no tour

        Organization.objects.create( uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

        response = self.client.get( reverse( 'explain' ) )
        self.assertTrue( response.context[ 'tour_available' ] )           # seeded -> tour offered

    def test_authentication_enabled_in_the_cloud_default( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertTrue( response.context[ 'authentication_enabled' ] )

    @override_settings( SUPPRESS_AUTHENTICATION = True )
    def test_authentication_disabled_when_self_hosted( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertFalse( response.context[ 'authentication_enabled' ] )  # no sign-up concept self-hosted


class HomeSignedInCtaTest( TestCase ):
    """The site root (`/`, HomeView) stays reachable for everyone and routes a signed-in visitor onward:
    an early user (only the read-only sample org) to "Add my data", an owner to their dashboard."""

    def test_early_user_is_offered_add_my_data( self ):
        Organization.objects.create( uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # a guest whose only org is the sample

        response = self.client.get( reverse( 'home' ) )

        self.assertTrue( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, reverse( 'dashboard' ) )

    def test_owner_is_pointed_to_the_dashboard( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'home' ) )

        self.assertFalse( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, reverse( 'dashboard' ) )
        self.assertNotContains( response, reverse( 'add_my_data' ) )


class DashboardEarlyUserTest( TestCase ):
    """The dashboard promotes "Add My Data" to an early user (only the sample org) and not once they have
    their own org -- driven by the `offer_add_my_data` context flag."""

    def test_promotes_add_my_data_to_an_early_user( self ):
        Organization.objects.create( uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # a guest whose only org is the sample

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertTrue( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, reverse( 'add_my_data' ) )

    def test_does_not_promote_once_they_own_an_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertFalse( response.context[ 'offer_add_my_data' ] )
