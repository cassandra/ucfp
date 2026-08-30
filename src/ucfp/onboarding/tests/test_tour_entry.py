"""`StartTourView` / `TourProfileView`: "Take a Tour" joins the visitor to the example org, switches to it,
and lands on the Profile step -- the *real* interview (`InterviewView`) rendered under the tour shell,
not the app nav. An anonymous visitor is minted a Guest first; a signed-in visitor is used as-is (no
conversion, no blocking). Unavailable when the example org is not seeded."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, tag
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.interview import first_section_of_flow
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.onboarding.constants import EXAMPLE_ORGANIZATION_NAME, EXAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.state import OnboardingState
from ucfp.onboarding.membership import join_example_org
from ucfp.onboarding.seeding import _seed_records, seed_example_org
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets

User = get_user_model()


@override_settings( SUPPRESS_AUTHENTICATION = False )
class StartTourTest( TestCase ):
    """Cloud mode: the tour funnel starts from an anonymous visitor, so pin authentication enabled --
    self-hosted has no anonymous visitor to convert (the singleton owner is always signed in)."""

    def _seed_example( self ):
        return Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )

    def _tour_profile_url( self ):
        return reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } )

    def _current_org_uuid( self ):
        return self.client.session.get( 'current_organization_uuid' )

    def test_anonymous_take_a_tour_mints_a_guest_and_enters( self ):
        example = self._seed_example()

        response = self.client.post( reverse( 'start_tour' ) )

        self.assertRedirects( response, self._tour_profile_url(), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )                               # one Guest minted
        member = OrganizationMember.objects.get( organization = example )          # joined as VIEWER
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )
        self.assertTrue( member.user.is_guest )
        self.assertEqual( self._current_org_uuid(), str( EXAMPLE_ORGANIZATION_UUID ) )  # switched to example

    def test_signed_in_visitor_enters_without_a_new_account( self ):
        example = self._seed_example()
        user = User.objects.create_user( email = 'v@x.test' )
        self.client.force_login( user )

        response = self.client.post( reverse( 'start_tour' ) )

        self.assertRedirects( response, self._tour_profile_url(), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )                               # no second account
        member = OrganizationMember.objects.get( organization = example, user = user )
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )
        self.assertEqual( self._current_org_uuid(), str( EXAMPLE_ORGANIZATION_UUID ) )

    def test_tour_profile_renders_the_real_interview_under_the_tour_shell( self ):
        _seed_records( self._seed_example() )                     # a real Profile (no forecast) to render
        self.client.post( reverse( 'start_tour' ) )              # enter as a VIEWER guest

        response = self.client.get( self._tour_profile_url() )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, '<title>Profile · Guided Tour · Landfall</title>', html = False )
        self.assertTemplateUsed( response, 'onboarding/tour/interview.html' )     # the tour's own page
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell
        self.assertTemplateUsed( response, 'inputs/interview/body.html' )         # the real interview body
        self.assertTemplateNotUsed( response, 'pages/app_base.html' )             # not the app chrome
        # The interview's navigation is retargeted to the tour route (stepper/Next), so a reload no longer
        # escapes to the real interview page; and a last section has no completion destination -> no Finish.
        self.assertEqual( response.context[ 'section_url_name' ], 'tour_profile' )
        self.assertIsNone( response.context[ 'completion_destination' ] )  # no Finish while browsing
        # Profile is not scenario context, so its title keeps no "Scenario >" qualifier and its nav is
        # single-step (the flag the shell branches on).
        self.assertFalse( response.context[ 'rail_scenario_mode' ] )

    def test_tour_scenario_shows_plans_and_assumptions_in_scenario_context( self ):
        _seed_records( self._seed_example() )                     # real Plans/Assumptions + example scenario
        self.client.post( reverse( 'start_tour' ) )

        url = reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'plans' ).key } )
        response = self.client.get( url )

        self.assertEqual( response.status_code, 200 )
        # The two scenario components are distinct pages, so each names its own part in the title.
        self.assertContains( response, '<title>Plans · Guided Tour · Landfall</title>', html = False )
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
        _seed_records( self._seed_example() )
        self.client.post( reverse( 'start_tour' ) )
        self.client.get(                                         # sets editing_scenario in the session
            reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'assumptions' ).key } ) )

        response = self.client.get(
            reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } ) )

        self.assertIsNone( response.context[ 'completion_destination' ] )  # not the app's Scenarios page

    def test_tour_forecast_is_unavailable_without_a_captured_run( self ):
        _seed_records( self._seed_example() )                     # records but no forecast run
        self.client.post( reverse( 'start_tour' ) )

        response = self.client.get( reverse( 'tour_forecast' ) )

        self.assertEqual( 404, response.status_code )            # DataNotAvailableError, not the run page

    def test_unseeded_example_makes_the_tour_unavailable( self ):
        response = self.client.post( reverse( 'start_tour' ) )

        self.assertEqual( 404, response.status_code )                             # DataNotAvailableError
        self.assertFalse( User.objects.exists() )                                 # no orphan Guest minted

    def test_step_nav_lights_the_current_step( self ):
        # `tour_active_step` drives the shell's four-step nav. The non-trivial case: Plans and Assumptions
        # are the one `tour_scenario` view, so the active step must follow the section's flow, not the URL.
        _seed_records( self._seed_example() )
        self.client.post( reverse( 'start_tour' ) )

        def step_at( url ):
            return self.client.get( url ).context[ 'tour_active_step' ]

        self.assertEqual( 1, step_at(
            reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } ) ) )
        self.assertEqual( 2, step_at(
            reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'plans' ).key } ) ) )
        self.assertEqual( 3, step_at(
            reverse( 'tour_scenario', kwargs = { 'section': first_section_of_flow( 'assumptions' ).key } ) ) )

    def test_the_shell_nav_links_target_the_live_flow_sections( self ):
        # The shell's step links must track the section registry. A renamed first-section (e.g.
        # retirement -> retirement-plan) 404s on click while `{% url %}` reversal still succeeds for any
        # string, so assert the rendered nav carries the *current* first-section URL of each flow.
        _seed_records( self._seed_example() )
        self.client.post( reverse( 'start_tour' ) )
        shell = self.client.get(
            reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } ) )
        for flow, url_name in ( ( 'profile', 'tour_profile' ), ( 'plans', 'tour_scenario' ),
                                ( 'assumptions', 'tour_scenario' ) ):
            self.assertContains( shell, reverse(
                url_name, kwargs = { 'section': first_section_of_flow( flow ).key } ) )


@tag( 'e2e' )
class TourForecastRenderTest( TestCase ):
    """The Forecast step renders the example org's captured run under the tour shell -- needs a real
    captured run (seed_example_org runs a forecast), so it is e2e."""

    def setUp( self ):
        seed_default_parameter_sets()
        User.objects.create_superuser( email = 'admin@x.test', password = 'x' )
        seed_example_org()                                        # example org + a captured forecast run

    def test_tour_forecast_renders_the_example_run_under_the_tour_shell( self ):
        self.client.post( reverse( 'start_tour' ) )              # enter as a VIEWER guest

        response = self.client.get( reverse( 'tour_forecast' ) )

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'onboarding/tour/forecast.html' )
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell
        self.assertTemplateUsed( response, 'planning/pages/run_table_panel.html' )  # summary + table
        self.assertTemplateUsed( response, 'planning/pages/run_books_table.html' )  # the real books table
        self.assertTemplateNotUsed( response, 'pages/app_base.html' )             # not the app chrome
        self.assertEqual( 4, response.context[ 'tour_active_step' ] )             # the shell lights Forecast


@override_settings( SUPPRESS_AUTHENTICATION = False )
class AddMyDataTest( TestCase ):
    """`AddMyDataView`: the universal graduation -- mint a Guest if anonymous, then ensure an organization
    of the user's own (not the example) and land on the Profile to start entering data. Pinned to cloud
    mode: the anonymous-visitor and no-minting-on-GET assertions have no analogue self-hosted, where the
    singleton owner is always signed in."""

    def _own_org( self, user ):
        return OrganizationMember.objects.get(
            user = user, organization_role = OrganizationRole.OWNER ).organization

    def test_anonymous_add_my_data_mints_a_guest_in_their_own_org( self ):
        response = self.client.post( reverse( 'add_my_data' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )
        own = self._own_org( User.objects.get() )
        self.assertNotEqual( str( own.uuid ), str( EXAMPLE_ORGANIZATION_UUID ) )   # their own, not the example
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

    def test_tour_guest_add_my_data_switches_off_the_example( self ):
        example = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # guest, VIEWER of example, current-org=example

        response = self.client.post( reverse( 'add_my_data' ) )

        self.assertRedirects( response, reverse( 'flow_profile' ), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )              # no second account
        user = User.objects.get()
        own = self._own_org( user )                             # a fresh owned org, not the example
        self.assertNotEqual( str( own.uuid ), str( EXAMPLE_ORGANIZATION_UUID ) )
        self.assertEqual( self.client.session.get( 'current_organization_uuid' ), str( own.uuid ) )
        # still a member of the example -- reachable again via the switcher, just no longer the current org
        self.assertTrue( OrganizationMember.objects.filter( user = user, organization = example ).exists() )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class FeaturePageAddMyDataTest( TestCase ):
    """The real feature pages (here the Profile interview under the app chrome) promote "Add my data" to a
    user whose only org is the read-only example, and suppress the guest "save your work" email banner there
    -- there is nothing of *theirs* to save yet. Once they own an org, neither prompt shows. Pinned to cloud
    mode: the example-only state cannot arise self-hosted, where the singleton always owns its org."""

    _CTA_COPY   = "Add your own to build your real plan"
    _EMAIL_COPY = "add an email so you don't lose it"

    def _profile_url( self ):
        return reverse( 'interview_section',
                        kwargs = { 'section': first_section_of_flow( 'profile' ).key } )

    def test_example_only_user_sees_add_my_data_and_not_the_email_banner( self ):
        _seed_records( Organization.objects.create(               # a complete example Profile to render
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME ) )
        self.client.post( reverse( 'start_tour' ) )              # guest VIEWER, current-org = example

        response = self.client.get( self._profile_url() )        # the REAL interview, app chrome

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'pages/app_base.html' )        # not the tour shell
        self.assertTrue( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, self._CTA_COPY )                   # the "Add my data" prompt
        self.assertNotContains( response, self._EMAIL_COPY )              # email pitch stands down

    def test_forecast_hub_promotes_add_my_data_to_a_example_only_user( self ):
        _seed_records( Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME ) )
        self.client.post( reverse( 'start_tour' ) )              # guest VIEWER, current-org = example

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


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ExplainGatingTest( TestCase ):
    """`ExplainView` exposes the two deployment-mode flags its template gates cloud-only chrome on:
    `tour_available` (is the example org seeded, so "Take a tour" can run) and `authentication_enabled`
    (is sign-in in play, so the "free, no sign-up" reassurance applies). This tests that contract, not
    the page's evolving layout/copy. Pinned to cloud mode by default; the one self-hosted case re-pins
    `SUPPRESS_AUTHENTICATION=True` at the method level."""

    def test_tour_available_reflects_a_seeded_example_org( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertEqual( 200, response.status_code )
        self.assertFalse( response.context[ 'tour_available' ] )          # no example seeded -> no tour

        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )

        response = self.client.get( reverse( 'explain' ) )
        self.assertTrue( response.context[ 'tour_available' ] )           # seeded -> tour offered

    def test_authentication_enabled_in_the_cloud_default( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertEqual( 200, response.status_code )
        self.assertTrue( response.context[ 'authentication_enabled' ] )

    @override_settings( SUPPRESS_AUTHENTICATION = True )
    def test_authentication_disabled_when_self_hosted( self ):
        response = self.client.get( reverse( 'explain' ) )
        self.assertEqual( 200, response.status_code )
        self.assertFalse( response.context[ 'authentication_enabled' ] )  # no sign-up concept self-hosted


@override_settings( SUPPRESS_AUTHENTICATION = False )
class HomeOnboardingCtaTest( TestCase ):
    """The site root (`/`, HomeView) stays reachable for everyone and resolves one of three onboarding states
    (`onboarding.state`): an anonymous visitor learns how it works, an early user (only the read-only
    example) starts their own plan, an owner goes to their dashboard. The self-hosted singleton is always an
    owner. A *signed-in* visitor must never see two competing gold actions (the former bug); an anonymous
    visitor legitimately sees the same "See how it works" action repeated in the closing marketing band.
    Pinned to cloud mode by default; the self-hosted-singleton case re-pins `SUPPRESS_AUTHENTICATION=True`
    at the method level."""

    @staticmethod
    def _gold_count( response ):
        # The gold ("btn-cta") action is the page's single focal action; this encodes that CSS-class
        # contract to guard the one-gold-per-signed-in-state rule.
        return response.content.decode().count( 'btn-cta' )

    def test_anonymous_visitor_learns_how_it_works( self ):
        response = self.client.get( reverse( 'home' ) )

        self.assertEqual( OnboardingState.ANONYMOUS.value, response.context[ 'onboarding_state' ] )
        self.assertContains( response, reverse( 'explain' ) )
        self.assertContains( response, reverse( 'user_signin' ) )        # the "already have an account?" line
        self.assertNotContains( response, reverse( 'dashboard' ) )
        self.assertEqual( 2, self._gold_count( response ) )              # hero + closing band, same action

    def test_early_user_starts_planning_with_a_single_gold_action( self ):
        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # a guest whose only org is the example

        response = self.client.get( reverse( 'home' ) )

        self.assertEqual( OnboardingState.EXAMPLE_ONLY.value, response.context[ 'onboarding_state' ] )
        self.assertContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, reverse( 'dashboard' ) )
        self.assertEqual( 1, self._gold_count( response ) )             # one gold, not two (the fixed bug)
        self.assertNotContains( response, reverse( 'user_signin' ) )    # the home sign-in bar is anonymous-only

    def test_owner_is_pointed_to_the_dashboard( self ):
        # The realistic owner is also auto-joined to the example as a VIEWER, so this exercises the
        # example-excluding `working_organization` -- they still resolve to OWN_ORG, not EXAMPLE_ONLY.
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        join_example_org( user )
        self.client.force_login( user )

        response = self.client.get( reverse( 'home' ) )

        self.assertEqual( OnboardingState.OWN_ORG.value, response.context[ 'onboarding_state' ] )
        self.assertContains( response, reverse( 'go_to_dashboard' ) )   # the CTA that lands on the dashboard
        self.assertNotContains( response, reverse( 'add_my_data' ) )
        self.assertEqual( 1, self._gold_count( response ) )
        self.assertNotContains( response, reverse( 'user_signin' ) )    # a Verified owner has no use for it

    @override_settings( SUPPRESS_AUTHENTICATION = True )
    def test_self_hosted_singleton_is_an_owner( self ):
        # The self-hosted identity middleware signs in a singleton owning its org, so home resolves to
        # OWN_ORG with no anonymous chrome.
        response = self.client.get( reverse( 'home' ) )

        self.assertEqual( OnboardingState.OWN_ORG.value, response.context[ 'onboarding_state' ] )
        self.assertContains( response, reverse( 'go_to_dashboard' ) )   # the CTA that lands on the dashboard
        self.assertNotContains( response, reverse( 'user_signin' ) )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class DashboardEarlyUserTest( TestCase ):
    """The dashboard promotes "Add My Data" to an early user (only the example org) and not once they have
    their own org -- driven by the `offer_add_my_data` context flag. Pinned to cloud mode: the example-only
    early-user state cannot arise self-hosted, where the singleton always owns its org."""

    def test_promotes_add_my_data_to_an_early_user( self ):
        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # a guest whose only org is the example

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertTrue( response.context[ 'offer_add_my_data' ] )
        self.assertContains( response, reverse( 'add_my_data' ) )

    def test_does_not_promote_once_they_own_an_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertFalse( response.context[ 'offer_add_my_data' ] )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class DashboardAccountSigninOfferTest( TestCase ):
    """The dashboard rescues an *accidental Guest* -- one who has an existing account but was funnelled into a
    throwaway one before finding the sign-in path -- with a quiet "already have an account?" sign-in. It is
    offered only while the Guest has nothing worth keeping (the collision flow's own "no content" signal, so
    signing in loses nothing); a Guest who has begun real work, and a Verified user, do not see it. Cloud
    mode: the offer is meaningless self-hosted."""

    def test_offered_to_a_guest_with_nothing_saved( self ):
        guest = User.objects.create_guest()
        Organization.objects.create_for_owner( guest, 'Mine' )
        self.client.force_login( guest )

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertTrue( response.context[ 'offer_account_signin' ] )
        self.assertContains( response, reverse( 'guest_signin' ) )

    def test_not_offered_once_the_guest_has_entered_content( self ):
        guest = User.objects.create_guest()
        organization = Organization.objects.create_for_owner( guest, 'Mine' )
        save_profile( organization, Profile( subjects = [ SubjectProfile(
            handle = 'subject', name = 'Alice', birthdate = date( 1980, 1, 1 ) ) ] ) )
        self.client.force_login( guest )

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertFalse( response.context[ 'offer_account_signin' ] )
        self.assertNotContains( response, reverse( 'guest_signin' ) )

    def test_not_offered_to_a_verified_user( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'dashboard' ) )

        self.assertFalse( response.context[ 'offer_account_signin' ] )
        self.assertNotContains( response, reverse( 'guest_signin' ) )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class GoToOwnDashboardTest( TestCase ):
    """`GoToOwnDashboardView`: the home "Go to your dashboard" CTA lands on the dashboard, switching the
    session off the read-only example when the visitor is still on it (e.g. arrived from the tour), but
    leaving a deliberately-selected own household alone. Exercises the preserve-current behavior of
    `ensure_own_organization`."""

    def _current( self ):
        return self.client.session.get( 'current_organization_uuid' )

    def test_switches_off_the_example_to_the_users_own_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )
        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.client.force_login( user )
        self.client.post( reverse( 'start_tour' ) )               # arrive from the tour: current = example
        self.assertEqual( self._current(), str( EXAMPLE_ORGANIZATION_UUID ) )   # precondition

        response = self.client.post( reverse( 'go_to_dashboard' ) )

        self.assertRedirects( response, reverse( 'dashboard' ), fetch_redirect_response = False )
        self.assertEqual( self._current(), str( own.uuid ) )      # switched to their own org
        self.assertTrue(                                          # example membership is never revoked
            OrganizationMember.objects.filter(
                user = user, organization__uuid = EXAMPLE_ORGANIZATION_UUID ).exists() )

    def test_leaves_a_deliberately_chosen_household_untouched( self ):
        # A multi-org owner on their non-default household must not be reset to the default one.
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'First' )
        second = Organization.objects.create_for_owner( user, 'Second' )
        self.client.force_login( user )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( second.uuid )
        session.save()

        response = self.client.post( reverse( 'go_to_dashboard' ) )

        self.assertRedirects( response, reverse( 'dashboard' ), fetch_redirect_response = False )
        self.assertEqual( self._current(), str( second.uuid ) )   # unchanged, not reset to the default

    def test_get_does_not_switch_the_session( self ):
        # POST-only, so a crawled GET never mutates the org selection.
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'go_to_dashboard' ) )

        self.assertEqual( 405, response.status_code )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ExplainCtaStateTest( TestCase ):
    """The Explain page's graduation CTA tracks the shared onboarding state (`onboarding.state`), so it stops
    soliciting a returning visitor to "try" what they have already begun: a cold visitor is invited to "Try
    it now", a visitor still on the example graduates with "Start planning", and a user with their own plan
    is sent to their dashboard. Pinned to cloud mode: the anonymous and example-only states cannot arise
    self-hosted, where the singleton always owns its org."""

    def test_anonymous_visitor_is_invited_to_try_it_now( self ):
        response = self.client.get( reverse( 'explain' ) )

        self.assertContains( response, 'Try it now' )
        self.assertContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, reverse( 'go_to_dashboard' ) )

    def test_example_only_visitor_graduates_with_start_planning( self ):
        Organization.objects.create( uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.client.post( reverse( 'start_tour' ) )              # a guest whose only org is the example

        response = self.client.get( reverse( 'explain' ) )

        self.assertContains( response, 'Start planning' )
        self.assertContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, 'Try it now' )
        self.assertNotContains( response, reverse( 'go_to_dashboard' ) )

    def test_owner_is_pointed_to_their_dashboard( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'explain' ) )

        self.assertContains( response, reverse( 'go_to_dashboard' ) )
        self.assertNotContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, 'Try it now' )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class TourGraduationCtaTest( TestCase ):
    """The tour shell's one gold action tracks the shared onboarding state (`onboarding.state`): a visitor
    still on the example graduates with "Start planning", while a user who already has their own plan is
    sent to their dashboard rather than re-invited to start one. Pinned to cloud mode: the example-only
    state cannot arise self-hosted."""

    def _tour_profile_url( self ):
        return reverse( 'tour_profile', kwargs = { 'section': first_section_of_flow( 'profile' ).key } )

    def test_example_only_guest_sees_start_planning( self ):
        _seed_records( Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME ) )
        self.client.post( reverse( 'start_tour' ) )              # guest VIEWER, current-org = example

        response = self.client.get( self._tour_profile_url() )

        self.assertContains( response, 'Start planning' )
        self.assertContains( response, reverse( 'add_my_data' ) )
        self.assertNotContains( response, reverse( 'go_to_dashboard' ) )

    def test_owner_on_the_tour_is_sent_to_their_dashboard( self ):
        _seed_records( Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME ) )
        user = User.objects.create_user( email = 'o@x.test' )
        Organization.objects.create_for_owner( user, 'Mine' )    # their own plan, so state is OWN_ORG
        self.client.force_login( user )
        self.client.post( reverse( 'start_tour' ) )              # browse the example: current-org = example

        response = self.client.get( self._tour_profile_url() )

        self.assertContains( response, reverse( 'go_to_dashboard' ) )
        self.assertNotContains( response, 'Start planning' )
        self.assertNotContains( response, reverse( 'add_my_data' ) )
