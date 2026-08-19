"""The household display settings: the timezone field/property and its settings form.

The display timezone is a Profile-level choice from a curated IANA list, defaulting to US Central. It
governs how stored (UTC) datetimes -- run timestamps and default run names -- are shown, via the zone
`ensure_organization` activates for the request. These tests pin the model default and `tzinfo`
resolution, and the form's initial/apply/validation.
"""
from zoneinfo import ZoneInfo

from django.test import TestCase

from organization.constants import DEFAULT_TIMEZONE_NAME
from organization.forms import OrganizationSettingsForm
from organization.models import Organization


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
