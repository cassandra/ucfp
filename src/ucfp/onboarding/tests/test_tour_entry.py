"""`StartTourView`: "Take a Tour" joins the visitor to the sample org, switches to it, and lands on the
tour shell. An anonymous visitor is minted a Guest first; a signed-in visitor is used as-is (no
conversion, no blocking). Unavailable when the sample org is not seeded."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID

User = get_user_model()


class StartTourTest( TestCase ):

    def _seed_sample( self ):
        return Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

    def _current_org_uuid( self ):
        return self.client.session.get( 'current_organization_uuid' )

    def test_anonymous_take_a_tour_mints_a_guest_and_enters( self ):
        sample = self._seed_sample()

        response = self.client.post( reverse( 'start_tour' ) )

        self.assertRedirects( response, reverse( 'tour_home' ), fetch_redirect_response = False )
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

        self.assertRedirects( response, reverse( 'tour_home' ), fetch_redirect_response = False )
        self.assertEqual( User.objects.count(), 1 )                               # no second account
        member = OrganizationMember.objects.get( organization = sample, user = user )
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )
        self.assertEqual( self._current_org_uuid(), str( SAMPLE_ORGANIZATION_UUID ) )

    def test_tour_home_renders_under_the_tour_shell( self ):
        self._seed_sample()
        self.client.post( reverse( 'start_tour' ) )                               # enter first

        response = self.client.get( reverse( 'tour_home' ) )

        self.assertEqual( response.status_code, 200 )
        self.assertTemplateUsed( response, 'onboarding/tour_home.html' )
        self.assertTemplateUsed( response, 'pages/tour_base.html' )               # the no-nav tour shell

    def test_unseeded_sample_makes_the_tour_unavailable( self ):
        response = self.client.post( reverse( 'start_tour' ) )

        self.assertNotEqual( response.status_code, 302 )                          # not forwarded into a tour
        self.assertFalse( User.objects.exists() )                                 # no orphan Guest minted
