"""`join_example_org`: the best-effort, idempotent auto-join that makes a new user a read-only VIEWER of
the seeded example organization (the example-data preview relies on this membership)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.onboarding.constants import EXAMPLE_ORGANIZATION_NAME, EXAMPLE_ORGANIZATION_UUID
from ucfp.onboarding.membership import (
    is_example_organization, join_example_org, example_organization, working_organization )

User = get_user_model()


class IsExampleOrganizationTest( TestCase ):
    """`is_example_organization`: identifies the reserved example org so prompts about the user's own data
    can stand down while they merely view the example."""

    def test_true_for_the_example_org( self ):
        example = Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )
        self.assertTrue( is_example_organization( example ) )

    def test_false_for_another_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        self.assertFalse( is_example_organization( Organization.objects.create_for_owner( user, 'Mine' ) ) )

    def test_false_for_none( self ):
        self.assertFalse( is_example_organization( None ) )


class JoinExampleOrgTest( TestCase ):

    def _seed_example( self ):
        return Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )

    def test_joins_the_new_user_as_a_viewer( self ):
        organization = self._seed_example()
        user = User.objects.create_user( email = 'v@x.test' )

        self.assertTrue( join_example_org( user ) )

        member = OrganizationMember.objects.get( organization = organization, user = user )
        self.assertEqual( member.organization_role, OrganizationRole.VIEWER )

    def test_is_idempotent( self ):
        self._seed_example()
        user = User.objects.create_user( email = 'v@x.test' )

        join_example_org( user )
        join_example_org( user )

        self.assertEqual( OrganizationMember.objects.filter( user = user ).count(), 1 )

    def test_does_not_downgrade_an_existing_membership( self ):
        organization = self._seed_example()
        user = User.objects.create_user( email = 'o@x.test' )
        organization.members.create( user = user, organization_role = OrganizationRole.OWNER )

        join_example_org( user )

        self.assertEqual(
            OrganizationMember.objects.get( organization = organization, user = user ).organization_role,
            OrganizationRole.OWNER )

    def test_best_effort_no_op_when_the_example_org_is_unseeded( self ):
        user = User.objects.create_user( email = 'v@x.test' )

        self.assertIsNone( example_organization() )
        self.assertFalse( join_example_org( user ) )
        self.assertFalse( OrganizationMember.objects.filter( user = user ).exists() )


class WorkingOrganizationTest( TestCase ):
    """`working_organization`: the user's own org (not the read-only example), preferring one they own,
    or None when the example (or nothing) is all they have."""

    def _seed_example( self ):
        return Organization.objects.create(
            uuid = EXAMPLE_ORGANIZATION_UUID, name = EXAMPLE_ORGANIZATION_NAME )

    def test_returns_an_owned_org( self ):
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )

        self.assertEqual( working_organization( user ), own )

    def test_is_none_when_only_the_example( self ):
        self._seed_example()
        user = User.objects.create_user( email = 'v@x.test' )
        join_example_org( user )                                  # VIEWER of the example only

        self.assertIsNone( working_organization( user ) )

    def test_is_none_with_no_memberships( self ):
        self.assertIsNone( working_organization( User.objects.create_user( email = 'n@x.test' ) ) )

    def test_prefers_an_owned_org_over_the_example( self ):
        self._seed_example()
        user = User.objects.create_user( email = 'o@x.test' )
        own = Organization.objects.create_for_owner( user, 'Mine' )
        join_example_org( user )                                  # also a VIEWER of the example

        self.assertEqual( working_organization( user ), own )    # the example is never the working org
