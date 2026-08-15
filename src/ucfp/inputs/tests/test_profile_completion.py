"""`profile_completion_blockers`: the "why is my profile incomplete" reasons.

Sections mark complete on visit (so the user can jump around freely), which means a fully walked profile
can still be incomplete for want of a required datum. The blockers explain that -- but only once the walk
is done, so they never pre-empt errors while the user is still entering. Today the sole hard requirement
is a person: it is what sets the filing status a run cannot run without.
"""
from datetime import date

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from organization.models import Organization

from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.state import profile_advisories, profile_completion_blockers
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.planning.tests.support import forecast_profile


def _complete_profile_without_accounts() -> Profile:
    """A profile that can complete (a person and a housing choice) but has no funded account."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _mark_all_profile_sections_reviewed( record, profile ):
    """Acknowledge every applicable profile-flow section -- the state after Next-ing through the whole
    walk."""
    record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                     if flow_of( section ) == 'profile' and section.form is not None ]
    record.save()


class ProfileCompletionBlockersTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Blockers' )

    def test_no_blockers_while_the_walk_is_in_progress( self ):
        # No sections acknowledged yet: still walking, so nothing is surfaced (the stepper shows progress).
        record = save_profile( self.org, Profile() )
        self.assertEqual( profile_completion_blockers( record ), [] )

    def test_walked_without_a_person_reports_the_missing_person( self ):
        profile = Profile()                                   # every section walkable, but no subject added
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertIn( 'Add at least one person.', profile_completion_blockers( record ) )

    def test_walked_without_a_housing_choice_reports_it( self ):
        # A person is present (so no person blocker), but the own/rent/neither question is unanswered.
        profile = Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE )             # home_tenure defaults to None
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_completion_blockers( record ),
                          [ 'Choose whether you own or rent your home.' ] )

    def test_a_walked_profile_with_a_person_has_no_blockers( self ):
        profile = forecast_profile()                          # carries a subject (and so a filing status)
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_completion_blockers( record ), [] )


class ProfileAdvisoriesTest( TestCase ):
    """profile_advisories: quiet FYIs for a *complete* profile. Today: no funded account. Gated on
    completeness, so an incomplete (still-blocked) profile shows none."""

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Advisories' )

    def test_a_complete_profile_with_no_funded_account_is_noted( self ):
        profile = _complete_profile_without_accounts()
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_advisories( record ), [ 'No account balances entered yet.' ] )

    def test_a_funded_profile_has_no_advisory( self ):
        profile = forecast_profile()                          # has Cash, so an account is funded
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_advisories( record ), [] )

    def test_an_incomplete_profile_shows_no_advisory( self ):
        # Gated on completeness: a profile still missing its person shows the blocker, not FYIs.
        profile = Profile()
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_advisories( record ), [] )


class InterviewStatusRegionTest( SimpleTestCase ):
    """The `interview_status.html` region -- the badge and blockers antinode re-renders on each section
    advance. It always carries the id (the replace target), escalates from grey to danger only in the
    walked-but-blocked state, and is empty for a flow that carries no status."""

    def _render( self, context ):
        return render_to_string( 'inputs/interview/interview_status.html', context )

    def test_walked_and_blocked_shows_danger_and_the_reason( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': False,
                               'profile_blockers': [ 'Add at least one person.' ] } )
        self.assertIn( 'id="interview-status"', html )
        self.assertIn( 'badge-danger', html )
        self.assertIn( 'Add at least one person.', html )

    def test_complete_shows_success( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': True, 'profile_blockers': [] } )
        self.assertIn( 'badge-success', html )
        self.assertNotIn( 'badge-danger', html )

    def test_walk_in_progress_stays_neutral_grey( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': False, 'profile_blockers': [] } )
        self.assertIn( 'badge-secondary', html )               # neutral while walking -- not an error yet

    def test_a_non_profile_flow_is_an_empty_region( self ):
        html = self._render( { 'flow': 'plans' } )
        self.assertIn( 'id="interview-status"', html )         # present as a no-op replace target...
        self.assertNotIn( 'badge', html )                      # ...but carries no status today

    def test_an_advisory_renders_as_an_info_alert( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': True, 'profile_blockers': [],
                               'profile_advisories': [ 'No account balances entered yet.' ] } )
        self.assertIn( 'No account balances entered yet.', html )
        self.assertIn( 'alert-info', html )                    # a noticeable info FYI...
        self.assertNotIn( 'alert-danger', html )               # ...distinct from the error blocker
