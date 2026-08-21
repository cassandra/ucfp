"""`join_sample_org`: the best-effort, idempotent auto-join that makes a new user a read-only VIEWER of
the seeded sample organization (the sample-data preview relies on this membership)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.membership import join_sample_org, sample_organization

User = get_user_model()


class JoinSampleOrgTest( TestCase ):

    def _seed_sample( self ):
        return Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

    def test_joins_the_new_user_as_a_viewer( self ):
        organization = self._seed_sample()
        user = User.objects.create_user( email = 'v@x.test' )

        self.assertTrue( join_sample_org( user ) )

        member = OrganizationMember.objects.get( organization = organization, user = user )
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )

    def test_is_idempotent( self ):
        self._seed_sample()
        user = User.objects.create_user( email = 'v@x.test' )

        join_sample_org( user )
        join_sample_org( user )

        self.assertEqual( OrganizationMember.objects.filter( user = user ).count(), 1 )

    def test_does_not_downgrade_an_existing_membership( self ):
        organization = self._seed_sample()
        user = User.objects.create_user( email = 'o@x.test' )
        organization.members.create( user = user, organization_role = OrganizationRole.OWNER )

        join_sample_org( user )

        self.assertEqual(
            OrganizationMember.objects.get( organization = organization, user = user ).organization_role,
            OrganizationRole.OWNER )

    def test_best_effort_no_op_when_the_sample_org_is_unseeded( self ):
        user = User.objects.create_user( email = 'v@x.test' )

        self.assertIsNone( sample_organization() )
        self.assertFalse( join_sample_org( user ) )
        self.assertFalse( OrganizationMember.objects.filter( user = user ).exists() )
