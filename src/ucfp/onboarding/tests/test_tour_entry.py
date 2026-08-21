"""`StartTourView` / `TourProfileView`: "Take a Tour" joins the visitor to the sample org, switches to it,
and lands on the Profile step -- the *real* interview (`InterviewView`) rendered under the tour shell,
not the app nav. An anonymous visitor is minted a Guest first; a signed-in visitor is used as-is (no
conversion, no blocking). Unavailable when the sample org is not seeded."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.interview import first_section_of_flow
from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.seeding import _seed_records

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
        self.assertTemplateUsed( response, 'onboarding/tour/profile.html' )       # the tour's own page
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell
        self.assertTemplateUsed( response, 'inputs/interview/body.html' )         # the real interview body
        self.assertTemplateNotUsed( response, 'pages/app_base.html' )             # not the app chrome
        # The interview's navigation is retargeted to the tour route, so stepper/Next/Finish stay in the
        # tour (a reload no longer escapes to the real interview page).
        self.assertEqual( response.context[ 'section_url_name' ], 'tour_profile' )
        self.assertIn( '/tour/profile/', response.context[ 'completion_destination' ] )

    def test_unseeded_sample_makes_the_tour_unavailable( self ):
        response = self.client.post( reverse( 'start_tour' ) )

        self.assertNotEqual( response.status_code, 302 )                          # not forwarded into a tour
        self.assertFalse( User.objects.exists() )                                 # no orphan Guest minted
