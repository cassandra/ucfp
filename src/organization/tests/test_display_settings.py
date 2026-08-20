"""The household display settings: the timezone field/property and its settings form.

The display timezone is a Profile-level choice from a curated IANA list, defaulting to US Central. It
governs how stored (UTC) datetimes -- run timestamps and default run names -- are shown, via the zone
`ensure_organization` activates for the request. These tests pin the model default and `tzinfo`
resolution, and the form's initial/apply/validation.
"""
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.constants import DEFAULT_TIMEZONE_NAME
from organization.enums import OrganizationRole
from organization.forms import OrganizationSettingsForm
from organization.models import Organization, OrganizationMember


class OrganizationTimezoneModelTest( TestCase ):

    def test_defaults_to_us_central( self ):
        organization = Organization.objects.create( name = 'Household' )
        self.assertEqual( organization.display_timezone, DEFAULT_TIMEZONE_NAME )
        self.assertEqual( organization.display_timezone, 'America/Chicago' )

    def test_tzinfo_resolves_the_saved_zone( self ):
        organization = Organization.objects.create(
            name = 'Household', display_timezone = 'Asia/Tokyo' )
        self.assertEqual( organization.tzinfo, ZoneInfo( 'Asia/Tokyo' ) )


class OrganizationSettingsFormTest( TestCase ):

    def _organization( self ):
        return Organization.objects.create( name = 'Household' )

    def _post_data( self, organization, **overrides ):
        data = { 'currency': str( organization.currency ),
                 'timezone': organization.display_timezone }
        data.update( overrides )
        return data

    def test_initial_reflects_the_saved_timezone( self ):
        organization = self._organization()
        organization.display_timezone = 'Europe/Paris'
        organization.save( update_fields = [ 'display_timezone' ] )
        form = OrganizationSettingsForm( organization = organization )
        self.assertEqual( form.fields[ 'timezone' ].initial, 'Europe/Paris' )

    def test_apply_persists_the_chosen_timezone( self ):
        organization = self._organization()
        form = OrganizationSettingsForm(
            self._post_data( organization, timezone = 'Asia/Tokyo' ), organization = organization )
        self.assertTrue( form.is_valid(), form.errors )
        form.apply( organization )
        organization.refresh_from_db()
        self.assertEqual( organization.display_timezone, 'Asia/Tokyo' )

    def test_rejects_a_timezone_outside_the_curated_list( self ):
        organization = self._organization()
        form = OrganizationSettingsForm(
            self._post_data( organization, timezone = 'Mars/Phobos' ), organization = organization )
        self.assertFalse( form.is_valid() )
        self.assertIn( 'timezone', form.errors )


class OrganizationSettingsHouseholdsTest( TestCase ):
    """The settings page's household list: the current household is flagged, other active
    memberships are offered (with their role), and a household the user has left is excluded."""

    def _user( self, email ):
        return get_user_model().objects.create_user( email = email )

    def test_households_context_marks_current_and_excludes_left( self ):
        user    = self._user( 'u@x.test' )
        current = Organization.objects.create_for_owner( user, 'Current' )
        other   = Organization.objects.create_for_owner( self._user( 'h@x.test' ), 'Other' )
        OrganizationMember.objects.create(
            organization = other, user = user, organization_role = OrganizationRole.MEMBER )
        left = Organization.objects.create_for_owner( self._user( 'g@x.test' ), 'Left' )
        OrganizationMember.objects.create(
            organization = left, user = user, organization_role = OrganizationRole.MEMBER ).deactivate()

        self.client.force_login( user )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( current.uuid )     # resolve `current` as the household
        session.save()

        households = self.client.get( reverse( 'organization_settings' ) ).context[ 'households' ]

        by_name = { row[ 'organization' ].name: row for row in households }
        self.assertEqual( set( by_name ), { 'Current', 'Other' } )       # the left household is not listed
        self.assertTrue(  by_name[ 'Current' ][ 'is_current' ] )
        self.assertFalse( by_name[ 'Other'   ][ 'is_current' ] )
        self.assertEqual( by_name[ 'Current' ][ 'role_label' ], OrganizationRole.OWNER.label )
        self.assertEqual( by_name[ 'Other'   ][ 'role_label' ], OrganizationRole.MEMBER.label )

    def test_read_only_member_cannot_save_settings( self ):
        # End to end: the write-gate refuses a VIEWER's settings POST (403) before the form runs, even
        # though the page renders (GET) for them.
        user  = self._user( 'viewer@x.test' )
        owner = self._user( 'owner@x.test' )
        organization = Organization.objects.create_for_owner( owner, 'Shared' )
        OrganizationMember.objects.create(
            organization = organization, user = user, organization_role = OrganizationRole.VIEWER )
        self.client.force_login( user )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( organization.uuid )
        session.save()

        self.assertEqual( self.client.get( reverse( 'organization_settings' ) ).status_code, 200 )
        self.assertEqual( self.client.post( reverse( 'organization_settings' ), {} ).status_code, 403 )
