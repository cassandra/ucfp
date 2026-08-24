"""save_profile's month-versioning policy: a new month *continues* the review state, it does not reset it.

Regression for the bug where editing a profile whose latest record was effective an earlier month (e.g.
seeded example data effective the prior January) minted a fresh current-month record with no acknowledged
sections -- so a fully-filled, complete profile suddenly read as incomplete on the first Next. Plans and
Assumptions are not month-versioned, so only the Profile showed it.
"""
from datetime import date

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.repository import (
    current_effective_date, latest_profile, save_profile, store_profile )
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.state import profile_is_complete
from ucfp.jurisdiction.enums import FilingStatus


def _complete_profile() -> Profile:
    """A profile that reads complete once every section is reviewed -- a person and a housing choice."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _profile_section_keys( profile ) -> list:
    return [ section.key for section in applicable_sections( profile )
             if flow_of( section ) == 'profile' and section.form is not None ]


def _record_in_month( organization, profile, effective, acknowledged ) -> ProfileRecord:
    """A ProfileRecord for a specific (typically prior) month -- built directly, since save_profile always
    writes the current month."""
    record = ProfileRecord(
        organization = organization, effective_date = effective,
        label = effective.strftime( '%B %Y' ), acknowledged_sections = list( acknowledged ) )
    store_profile( record, profile )
    record.save()
    return record


class SaveProfileMonthCarryForwardTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Carry' )

    def test_new_month_inherits_prior_month_acknowledged_sections( self ):
        profile = _complete_profile()
        prior   = _record_in_month(
            self.org, profile, date( 2020, 1, 1 ), _profile_section_keys( profile ) )
        self.assertTrue( profile_is_complete( prior ) )

        record = save_profile( self.org, profile )              # edited now -> a new month's record

        self.assertEqual( record.effective_date, current_effective_date() )
        self.assertNotEqual( record.effective_date, prior.effective_date )
        self.assertEqual( record.acknowledged_section_keys, prior.acknowledged_section_keys )
        # The user-facing symptom: completeness survives the month rollover.
        self.assertTrue( profile_is_complete( latest_profile( self.org ) ) )

    def test_first_ever_profile_has_no_acknowledged_sections( self ):
        # No prior record to carry from: a brand-new profile starts un-reviewed (no false completeness).
        record = save_profile( self.org, Profile() )
        self.assertEqual( record.acknowledged_section_keys, set() )

    def test_same_month_edit_reuses_the_record_and_keeps_acknowledged( self ):
        # Editing within the same month reuses the record, so its acknowledged sections are untouched.
        first = save_profile( self.org, _complete_profile() )
        first.acknowledged_sections = _profile_section_keys( _complete_profile() )
        first.save()

        again = save_profile( self.org, _complete_profile() )

        self.assertEqual( again.pk, first.pk )
        self.assertEqual( again.acknowledged_section_keys, first.acknowledged_section_keys )
