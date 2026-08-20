"""Tests for the organization switch view (selecting the current household)."""
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

logging.disable( logging.CRITICAL )

User = get_user_model()

_SESSION_KEY = 'current_organization_uuid'


def _user( email ):
    return User.objects.create_user( email = email )


def _add_member( org, user, role ):
    return OrganizationMember.objects.create(
        organization = org, user = user, organization_role = role )


class OrganizationSwitchViewTest( TestCase ):

    def _url( self, org ):
        return reverse( 'organization_switch', kwargs = { 'organization_uuid': org.uuid } )

    def test_switch_without_a_referer_selects_org_and_falls_back_to_home( self ):
        user = _user( 'u@x.test' )
        Organization.objects.create_for_owner( user, 'Owned' )
        other = _user( 'host@x.test' )
        joined = Organization.objects.create_for_owner( other, 'Joined' )
        _add_member( joined, user, OrganizationRole.MEMBER )
        self.client.force_login( user )

        response = self.client.post( self._url( joined ) )

        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response[ 'Location' ], reverse( 'home' ) )
        self.assertEqual( self.client.session.get( _SESSION_KEY ), str( joined.uuid ) )

    def test_switch_reloads_the_referring_page( self ):
        user = _user( 'u@x.test' )
        Organization.objects.create_for_owner( user, 'Owned' )
        other = _user( 'host@x.test' )
        joined = Organization.objects.create_for_owner( other, 'Joined' )
        _add_member( joined, user, OrganizationRole.MEMBER )
        self.client.force_login( user )
        settings_url = 'http://testserver' + reverse( 'organization_settings' )

        response = self.client.post( self._url( joined ), HTTP_REFERER = settings_url )

        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response[ 'Location' ], settings_url )
        self.assertEqual( self.client.session.get( _SESSION_KEY ), str( joined.uuid ) )

    def test_switch_ignores_an_offsite_referer( self ):
        user = _user( 'u@x.test' )
        Organization.objects.create_for_owner( user, 'Owned' )
        other = _user( 'host@x.test' )
        joined = Organization.objects.create_for_owner( other, 'Joined' )
        _add_member( joined, user, OrganizationRole.MEMBER )
        self.client.force_login( user )

        response = self.client.post( self._url( joined ), HTTP_REFERER = 'http://evil.example/x' )

        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response[ 'Location' ], reverse( 'home' ) )

    def test_cannot_switch_to_an_organization_the_user_does_not_belong_to( self ):
        user = _user( 'u@x.test' )
        Organization.objects.create_for_owner( user, 'Owned' )
        stranger = _user( 'stranger@x.test' )
        foreign = Organization.objects.create_for_owner( stranger, 'Foreign' )
        self.client.force_login( user )

        response = self.client.post( self._url( foreign ) )

        self.assertEqual( response.status_code, 404 )
        self.assertIsNone( self.client.session.get( _SESSION_KEY ) )

    def test_cannot_switch_to_an_inactive_membership( self ):
        user = _user( 'u@x.test' )
        Organization.objects.create_for_owner( user, 'Owned' )
        other = _user( 'host@x.test' )
        left = Organization.objects.create_for_owner( other, 'Left' )
        membership = _add_member( left, user, OrganizationRole.MEMBER )
        membership.deactivate()
        self.client.force_login( user )

        response = self.client.post( self._url( left ) )

        self.assertEqual( response.status_code, 404 )
        self.assertIsNone( self.client.session.get( _SESSION_KEY ) )

    def test_switching_away_and_back_retains_the_household_context( self ):
        # End-to-end through the real endpoint + session: a scoped selection under one household
        # survives switching away and back, rather than being reset.
        user = _user( 'u@x.test' )
        org_a = Organization.objects.create_for_owner( user, 'A' )
        org_b = Organization.objects.create_for_owner( user, 'B' )
        self.client.force_login( user )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( org_a.uuid )
        session[ 'organization_contexts' ] = {
            str( org_a.uuid ): { 'current_scenario_uuid': 'scenario-a' } }
        session.save()

        self.client.post( self._url( org_b ) )                      # switch away
        self.client.post( self._url( org_a ) )                      # ...and back

        session = self.client.session
        self.assertEqual( session[ _SESSION_KEY ], str( org_a.uuid ) )
        self.assertEqual(
            session[ 'organization_contexts' ][ str( org_a.uuid ) ][ 'current_scenario_uuid' ],
            'scenario-a' )

    def test_get_is_not_allowed( self ):
        user = _user( 'u@x.test' )
        org = Organization.objects.create_for_owner( user, 'Owned' )
        self.client.force_login( user )

        response = self.client.get( self._url( org ) )

        self.assertEqual( response.status_code, 405 )
