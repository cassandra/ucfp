"""`join_sample_org`: the best-effort, idempotent auto-join that makes a new user a read-only VIEWER of
the seeded sample organization (the sample-data preview relies on this membership)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.membership import (
    is_sample_organization, join_sample_org, sample_organization, working_organization )

User = get_user_model()


class IsSampleOrganizationTest( TestCase ):
    """`is_sample_organization`: identifies the reserved sample org so prompts about the user's own data
    can stand down while they merely view the sample."""

    def test_true_for_the_sample_org( self ):
        sample = Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )
        self.assertTrue( is_sample_organization( sample ) )

    def test_false_for_another_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        self.assertFalse( is_sample_organization( Organization.objects.create_for_owner( user, 'Mine' ) ) )

    def test_false_for_none( self ):
        self.assertFalse( is_sample_organization( None ) )


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


class WorkingOrganizationTest( TestCase ):
    """`working_organization`: the user's own org (not the read-only sample), preferring one they own,
    or None when the sample (or nothing) is all they have."""

    def _seed_sample( self ):
        return Organization.objects.create(
            uuid = SAMPLE_ORGANIZATION_UUID, name = SAMPLE_ORGANIZATION_NAME )

    def test_returns_an_owned_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )

        self.assertEqual( working_organization( user ), own )

    def test_is_none_when_only_the_sample( self ):
        self._seed_sample()
        user = User.objects.create_user( email = 'v@x.test' )
        join_sample_org( user )                                  # VIEWER of the sample only

        self.assertIsNone( working_organization( user ) )

    def test_is_none_with_no_memberships( self ):
        self.assertIsNone( working_organization( User.objects.create_user( email = 'n@x.test' ) ) )

    def test_prefers_an_owned_org_over_the_sample( self ):
        self._seed_sample()
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )
        join_sample_org( user )                                  # also a VIEWER of the sample

        self.assertEqual( working_organization( user ), own )    # the sample is never the working org
