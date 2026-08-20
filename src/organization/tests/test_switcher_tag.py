"""Tests for the `organization_switcher` navbar inclusion tag."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from testing.base_test_case import BaseTestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from organization.templatetags.organization_tags import organization_switcher

User = get_user_model()


def _context( user, organization ):
    """A minimal template context carrying the request attributes the tag reads."""
    request = RequestFactory().get( '/' )
    request.user = user
    request.organization = organization
    return { 'request': request }


class OrganizationSwitcherTagTestCase( BaseTestCase ):

    def test_inert_without_a_request( self ):
        self.assertEqual( organization_switcher( {} ), { 'show': False } )
        return

    def test_inert_for_an_anonymous_user( self ):
        organization = Organization.objects.create( name = 'Anon Household' )
        self.assertEqual(
            organization_switcher( _context( AnonymousUser(), organization ) ),
            { 'show': False } )
        return

    def test_inert_without_a_resolved_current_organization( self ):
        user = User.objects.create_user( email = 'u@example.com' )
        self.assertEqual(
            organization_switcher( _context( user, None ) ), { 'show': False } )
        return

    def test_single_membership_shows_the_current_household_without_switch_targets( self ):
        user = User.objects.create_user( email = 'solo@example.com' )
        organization = Organization.objects.create_for_owner( user, 'Solo' )

        result = organization_switcher( _context( user, organization ) )

        self.assertTrue( result[ 'show' ] )
        self.assertEqual( result[ 'current' ], organization )
        self.assertFalse( result[ 'has_others' ] )
        self.assertEqual( result[ 'other_organizations' ], [] )
        return

    def test_multiple_memberships_offer_the_other_households_as_targets( self ):
        user = User.objects.create_user( email = 'multi@example.com' )
        host = User.objects.create_user( email = 'host@example.com' )
        current = Organization.objects.create_for_owner( user, 'Current' )
        other = Organization.objects.create_for_owner( host, 'Other' )
        OrganizationMember.objects.create(
            organization = other, user = user, organization_role = OrganizationRole.MEMBER )

        result = organization_switcher( _context( user, current ) )

        self.assertTrue( result[ 'has_others' ] )
        self.assertEqual( result[ 'current' ], current )
        # The current household is the indicator, never its own switch target.
        self.assertEqual( result[ 'other_organizations' ], [ other ] )
        return

    def test_inactive_membership_is_not_a_switch_target( self ):
        user = User.objects.create_user( email = 'left@example.com' )
        host = User.objects.create_user( email = 'host2@example.com' )
        current = Organization.objects.create_for_owner( user, 'Current' )
        left = Organization.objects.create_for_owner( host, 'Left' )
        membership = OrganizationMember.objects.create(
            organization = left, user = user, organization_role = OrganizationRole.MEMBER )
        membership.deactivate()

        result = organization_switcher( _context( user, current ) )

        self.assertFalse( result[ 'has_others' ] )
        self.assertEqual( result[ 'other_organizations' ], [] )
        return
