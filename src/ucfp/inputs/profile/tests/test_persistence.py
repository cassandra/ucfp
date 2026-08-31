"""The profile monthly save/retrieve policy: mint, overwrite within the month, retain prior
months, and resolve the latest."""
from datetime import date

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.repository import (
    create_profile, current_effective_date, latest_profile, load_profile, save_profile,
    store_profile )
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus


def _completed_profile() -> Profile:
    """A fully valid profile (a person, a filing status, a housing choice) -- with every section
    acknowledged it reads as a finished snapshot, the retain-a-prior-month case."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _profile_flow_keys() -> list:
    """Every live profile-flow section key -- a record acknowledging all of them reads as fully walked."""
    return [ section.key for section in applicable_sections( Profile() )
             if flow_of( section ) == 'profile' and section.form is not None ]


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

    def test_save_retains_a_prior_completed_month_and_becomes_the_latest( self ):
        # A finished (fully walked) prior month is a retained snapshot: a later save mints a new current
        # month rather than overwriting it. (A first, still-in-progress profile is instead edited in place --
        # see test_profile_repository.)
        organization = self._organization()
        prior = ProfileRecord(
            organization = organization, effective_date = date( 2000, 1, 1 ), label = 'old',
            acknowledged_sections = _profile_flow_keys() )
        store_profile( prior, _completed_profile() )
        prior.save()
        save_profile( organization, Profile() )
        self.assertEqual(
            ProfileRecord.objects.filter( organization = organization ).count(), 2 )
        self.assertEqual( latest_profile( organization ).effective_date, current_effective_date() )
