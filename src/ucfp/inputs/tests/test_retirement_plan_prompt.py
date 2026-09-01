"""The Retirement plan section points visitors to the Social Security Timing calculator -- a one-way
prompt (it writes nothing back to the plan) so people can compare claiming ages before choosing one."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import PRIMARY_SUBJECT_HANDLE, Profile, SubjectProfile

User = get_user_model()


class RetirementPlanCalculatorPromptTest( TestCase ):

    def setUp( self ):
        self.owner = User.objects.create_user( email = 'owner@x.test' )
        self.org   = Organization.objects.create_for_owner( self.owner, 'Mine' )
        save_profile( self.org, Profile(
            subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1960, 1, 1 ) ) ] ) )
        self.client.force_login( self.owner )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( self.org.uuid )
        session.save()

    def test_the_retirement_plan_section_links_to_the_calculator( self ):
        response = self.client.get(
            reverse( 'interview_section', kwargs = { 'section': 'retirement-plan' } ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, reverse( 'calculators:ss_timing:inputs' ) )
        self.assertContains( response, 'Social Security Timing calculator' )
