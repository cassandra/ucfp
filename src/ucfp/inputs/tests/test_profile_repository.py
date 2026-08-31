"""save_profile's month policy and the explicit `advance_profile` refresh.

Each month's profile is an immutable snapshot: `save_profile` writes only the current month and never
overwrites a prior one (history is retained for later plan-vs-actual comparison). Advancing an aged
profile into the current month is the explicit job of `advance_profile`, which carries the facts
forward but keeps only the non-decaying (People) acknowledgments, so the volatile sections reopen for
review. Cross-month completeness is therefore no longer inherited on a silent edit -- it is the outcome
of an explicit, gated advance (the gate itself lands in a later phase).
"""
from datetime import date

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.interview import SUBJECTS_STEP, applicable_sections, flow_of
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.repository import (
    advance_profile, allow_profile_write_in_place, current_effective_date, latest_profile, load_profile,
    profile_is_outdated, save_profile, store_profile )
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.state import profile_is_complete
from ucfp.jurisdiction.enums import FilingStatus


def _complete_profile() -> Profile:
    """A profile that reads complete once every section is reviewed -- a person and a housing choice."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _walked_but_invalid_profile() -> Profile:
    """Every section can be acknowledged, yet a required fact is missing (no housing choice) -- fully walked
    but still incomplete. The gate deems it incomplete, so the in-place test must too, else the next
    cross-month edit strands the walk."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = None )


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


class SaveProfileMonthPolicyTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Save' )

    def test_editing_in_a_new_month_retains_the_prior_and_does_not_inherit_review( self ):
        # The latest record is an earlier month (e.g. seeded data). Saving now writes a *fresh*
        # current-month record: the prior month is kept as history, and the new month does not inherit
        # its reviewed state -- the aged snapshot is meant to be reviewed (via an explicit advance),
        # not silently carried as complete.
        profile = _complete_profile()
        prior   = _record_in_month(
            self.org, profile, date( 2020, 1, 1 ), _profile_section_keys( profile ) )
        self.assertTrue( profile_is_complete( prior ) )

        record = save_profile( self.org, profile )

        self.assertEqual( record.effective_date, current_effective_date() )
        self.assertNotEqual( record.effective_date, prior.effective_date )
        self.assertEqual( record.acknowledged_section_keys, set() )
        # The prior month survives untouched -- history is retained.
        prior.refresh_from_db()
        self.assertEqual( prior.acknowledged_section_keys, set( _profile_section_keys( profile ) ) )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 2 )

    def test_first_ever_profile_has_no_acknowledged_sections( self ):
        # No prior record: a brand-new profile starts un-reviewed (no false completeness).
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

    def test_a_sole_in_progress_profile_is_edited_in_place_across_a_month( self ):
        # A first profile, still incomplete and the only record: editing it in a later month continues it in
        # place -- no new record, its partial review state preserved, and re-dated to now (an unfinished
        # profile's "as of" is the present). This is the case the freshness gate must never treat as a copy.
        prior = _record_in_month( self.org, _complete_profile(), date( 2020, 1, 1 ), [ SUBJECTS_STEP ] )

        record = save_profile( self.org, _complete_profile() )

        self.assertEqual( record.pk, prior.pk )                                  # same record, in place
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 1 )   # no copy
        self.assertEqual( record.effective_date, current_effective_date() )      # re-dated to the present
        self.assertEqual( record.acknowledged_section_keys, { SUBJECTS_STEP } )  # review progress preserved

    def test_a_walked_but_invalid_sole_profile_is_edited_in_place_not_stranded( self ):
        # Regression: a fully walked but still-invalid profile (no housing choice) is in-progress, not a
        # snapshot -- so a later edit continues it in place rather than minting an empty-ack record that
        # strands the walk. Fixed by judging in-progress with the same completeness the gate uses.
        invalid = _walked_but_invalid_profile()
        prior   = _record_in_month( self.org, invalid, date( 2020, 1, 1 ), _profile_section_keys( invalid ) )

        record = save_profile( self.org, invalid )

        self.assertEqual( record.pk, prior.pk )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 1 )
        self.assertEqual( record.acknowledged_section_keys, set( _profile_section_keys( invalid ) ) )


class AllowProfileWriteInPlaceTest( TestCase ):
    """The two-clause guard: an edit is written in place only for a first, still-in-progress profile --
    incomplete AND the sole record. Completeness alone is not enough; history (a second record) forbids it."""

    def setUp( self ):
        self.org = Organization.objects.create( name = 'InPlace' )

    def _record( self, effective, acknowledged ):
        return _record_in_month( self.org, _complete_profile(), effective, acknowledged )

    def test_a_sole_incomplete_profile_qualifies( self ):
        self._record( date( 2020, 1, 1 ), [ SUBJECTS_STEP ] )
        self.assertTrue( allow_profile_write_in_place( self.org ) )

    def test_a_walked_but_invalid_profile_qualifies( self ):
        # Walked (every section acknowledged) but incomplete (no housing choice): the gate and this predicate
        # must agree it is in-progress, so it is edited in place rather than stranded.
        invalid = _walked_but_invalid_profile()
        _record_in_month( self.org, invalid, date( 2020, 1, 1 ), _profile_section_keys( invalid ) )
        self.assertTrue( allow_profile_write_in_place( self.org ) )

    def test_a_sole_complete_profile_does_not( self ):
        self._record( date( 2020, 1, 1 ), _profile_section_keys( _complete_profile() ) )
        self.assertFalse( allow_profile_write_in_place( self.org ) )

    def test_no_profile_does_not( self ):
        self.assertFalse( allow_profile_write_in_place( self.org ) )

    def test_an_incomplete_profile_with_history_does_not( self ):
        # A prior completed month is history; a later incomplete attempt must not be written onto it.
        self._record( date( 2020, 1, 1 ), _profile_section_keys( _complete_profile() ) )
        self._record( date( 2020, 2, 1 ), [ SUBJECTS_STEP ] )
        self.assertFalse( allow_profile_write_in_place( self.org ) )


class AdvanceProfileTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Advance' )

    def test_advance_carries_facts_forward_but_keeps_only_people_reviewed( self ):
        profile = _complete_profile()
        prior   = _record_in_month(
            self.org, profile, date( 2020, 1, 1 ), _profile_section_keys( profile ) )

        advanced = advance_profile( self.org )
        advanced.refresh_from_db()                           # prove the copy persisted + re-decrypts on read

        # A new current-month record, with the facts carried forward verbatim.
        self.assertEqual( advanced.effective_date, current_effective_date() )
        self.assertEqual( load_profile( advanced ), profile )
        self.assertEqual( load_profile( latest_profile( self.org ) ), profile )   # via an independent reload
        # Only the non-decaying People section stays reviewed; every volatile section reopens.
        self.assertEqual( advanced.acknowledged_section_keys, { SUBJECTS_STEP } )
        self.assertFalse( profile_is_complete( advanced ) )
        # The prior month is retained, unchanged.
        prior.refresh_from_db()
        self.assertEqual( prior.acknowledged_section_keys, set( _profile_section_keys( profile ) ) )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 2 )

    def test_advance_drops_people_too_when_it_was_never_reviewed( self ):
        # People is kept only if it had been reviewed; nothing is fabricated.
        _record_in_month( self.org, _complete_profile(), date( 2020, 1, 1 ), [ 'accounts' ] )
        advanced = advance_profile( self.org )
        self.assertEqual( advanced.acknowledged_section_keys, set() )

    def test_advance_is_idempotent_within_the_month( self ):
        _record_in_month(
            self.org, _complete_profile(), date( 2020, 1, 1 ), [ SUBJECTS_STEP ] )
        first  = advance_profile( self.org )
        first.acknowledge( 'accounts' )                       # some review happens on the advanced record
        second = advance_profile( self.org )                  # advancing again must not reset or duplicate it

        self.assertEqual( second.pk, first.pk )
        self.assertIn( 'accounts', second.acknowledged_section_keys )
        self.assertEqual( ProfileRecord.objects.filter( organization = self.org ).count(), 2 )


class ProfileIsOutdatedTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Outdated' )

    def test_no_profile_is_not_outdated( self ):
        self.assertFalse( profile_is_outdated( self.org ) )

    def test_a_prior_month_profile_is_outdated( self ):
        _record_in_month( self.org, _complete_profile(), date( 2020, 1, 1 ), [] )
        self.assertTrue( profile_is_outdated( self.org ) )

    def test_a_current_month_profile_is_not_outdated( self ):
        save_profile( self.org, _complete_profile() )         # writes the current month
        self.assertFalse( profile_is_outdated( self.org ) )

    def test_advancing_clears_the_outdated_signal( self ):
        _record_in_month( self.org, _complete_profile(), date( 2020, 1, 1 ), [] )
        advance_profile( self.org )
        self.assertFalse( profile_is_outdated( self.org ) )
        self.assertIsNotNone( latest_profile( self.org ) )
