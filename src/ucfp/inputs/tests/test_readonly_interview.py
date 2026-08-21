"""A read-only member does not mutate the household by viewing the interview.

Marking a section acknowledged (and seeding its defaults) rides a GET -- "presenting the section is the
acknowledgment" -- so the HTTP-method write-gate cannot catch it. The interview must skip that write for
a read-only member, or a viewer would silently change shared data just by browsing it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.inputs.interview import first_section_of_flow
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.profile.schemas import Profile

User = get_user_model()


class ReadonlyInterviewAcknowledgementTest( TestCase ):

    def setUp( self ):
        self.owner   = User.objects.create_user( email = 'owner@x.test' )
        self.org     = Organization.objects.create_for_owner( self.owner, 'Shared' )
        save_profile( self.org, Profile() )                 # a profile with nothing acknowledged yet
        self.section = first_section_of_flow( 'profile' )

    def _get_first_section_as( self, user ):
        self.client.force_login( user )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( self.org.uuid )
        session.save()
        return self.client.get(
            reverse( 'interview_section', kwargs = { 'section': self.section.key } ) )

    def test_viewer_view_does_not_acknowledge_the_section( self ):
        viewer = User.objects.create_user( email = 'viewer@x.test' )
        OrganizationMember.objects.create(
            organization = self.org, user = viewer, organization_role = OrganizationRole.VIEWER )

        response = self._get_first_section_as( viewer )

        self.assertEqual( response.status_code, 200 )           # a viewer can still read the section
        self.assertNotIn(
            self.section.key, latest_profile( self.org ).acknowledged_section_keys )

    def test_viewer_of_a_household_with_no_profile_is_told_there_is_no_data( self ):
        # A household a writer never set up has no Profile; entering it would mint one (plus the Default
        # Plans/Assumptions) -- writes the read-only gate refuses. A viewer must get a clear "no data yet"
        # message, not a generic authorization error.
        empty  = Organization.objects.create_for_owner(
            User.objects.create_user( email = 'owner2@x.test' ), 'Empty' )
        viewer = User.objects.create_user( email = 'v2@x.test' )
        OrganizationMember.objects.create(
            organization = empty, user = viewer, organization_role = OrganizationRole.VIEWER )
        self.client.force_login( viewer )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( empty.uuid )
        session.save()

        response = self.client.get( reverse( 'flow_profile' ) )

        self.assertContains( response, 'no Profile data set up yet', status_code = 404 )

    def test_viewer_of_a_household_with_no_plans_is_told_there_is_no_data( self ):
        # The Plans mint site is guarded like Profile: a read-only member opening the Plans flow on a
        # household with a Profile but no Plans gets the clear "no Plans data" message.
        household = Organization.objects.create_for_owner(
            User.objects.create_user( email = 'po@x.test' ), 'NoPlans' )
        save_profile( household, Profile() )                    # a Profile exists, but no Plans
        viewer = User.objects.create_user( email = 'pv@x.test' )
        OrganizationMember.objects.create(
            organization = household, user = viewer, organization_role = OrganizationRole.VIEWER )
        self.client.force_login( viewer )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( household.uuid )
        session.save()

        response = self.client.get( reverse( 'flow_plans' ), follow = True )

        self.assertContains( response, 'no Plans data set up yet', status_code = 404 )

    def test_read_only_interview_shows_a_navigation_next_not_the_save_button( self ):
        # The read-only advance is a plain navigation link, not the advance-and-save form.
        viewer = User.objects.create_user( email = 'nv@x.test' )
        OrganizationMember.objects.create(
            organization = self.org, user = viewer, organization_role = OrganizationRole.VIEWER )
        self.client.force_login( viewer )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( self.org.uuid )
        session.save()

        response = self.client.get(
            reverse( 'interview_section', kwargs = { 'section': self.section.key } ) )

        self.assertContains( response, '>Next</a>' )             # a read-only navigation link
        self.assertNotContains( response, '>Next</button>' )     # not the advance-and-save button

    def test_writer_view_still_acknowledges_the_section( self ):
        # The convenience write is unchanged for a member who may write -- the guard is scoped to
        # read-only members, not a behavior change for everyone.
        response = self._get_first_section_as( self.owner )

        self.assertEqual( response.status_code, 200 )
        self.assertIn(
            self.section.key, latest_profile( self.org ).acknowledged_section_keys )
