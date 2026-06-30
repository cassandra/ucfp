"""The profile monthly save/retrieve policy: mint, overwrite within the month, retain prior
months, and resolve the latest."""
from datetime import date

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.profile.repository import (
    create_profile, current_effective_date, latest_profile, load_profile, save_profile,
    store_profile )
from ucfp.inputs.profile.schemas import Profile


class ProfileMonthlyPersistenceTest( TestCase ):

    def _organization( self ) -> Organization:
        return Organization.objects.create( name = 'Org' )

    def test_create_mints_an_empty_current_month_profile( self ):
        organization = self._organization()
        record = create_profile( organization )
        self.assertEqual( record.effective_date, current_effective_date() )
        self.assertEqual( load_profile( record ), Profile() )

    def test_save_overwrites_within_the_current_month( self ):
        organization = self._organization()
        create_profile( organization )
        save_profile( organization, Profile() )
        self.assertEqual(
            ProfileRecord.objects.filter( organization = organization ).count(), 1 )

    def test_save_retains_a_prior_month_and_becomes_the_latest( self ):
        organization = self._organization()
        prior = ProfileRecord(
            organization = organization, effective_date = date( 2000, 1, 1 ), label = 'old' )
        store_profile( prior, Profile() )
        prior.save()
        save_profile( organization, Profile() )
        self.assertEqual(
            ProfileRecord.objects.filter( organization = organization ).count(), 2 )
        self.assertEqual( latest_profile( organization ).effective_date, current_effective_date() )
