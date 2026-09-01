"""Seeding a brand-new profile from a visitor's SessionFacts -- the carry-over from the login-free tools.

A visitor can use the calculators with no account; the household facts they enter are held in the session
(see `ucfp.session_facts`). When they start their own plan, their first profile is minted seeded from those
facts, as reviewable Profile facts rather than lost or shown-but-unsaved. Two levels are covered here: the
`create_profile` mapping (facts -> Profile), and the `_mint_profile` view helper that threads a request's
session facts into that mapping. The seed only ever fills a blank profile -- a profile is created only when
the household has none yet.
"""
from datetime import date
from decimal import Decimal

from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.profile.repository import create_profile, load_profile
from ucfp.inputs.profile.schemas import PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, Profile
from ucfp.inputs.views import _mint_profile
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.session_facts import PersonFacts, SessionFacts
from ucfp.session_state import SessionState


def _couple_facts() -> SessionFacts:
    """A couple who entered both people's birth year, benefit, and expected lifetime into the calculator."""
    return SessionFacts( people = [
        PersonFacts( birth_year = 1960, government_pension_monthly = Decimal( '3000' ),
                     life_expectancy = 88 ),
        PersonFacts( birth_year = 1962, government_pension_monthly = Decimal( '1200' ),
                     life_expectancy = 90 ) ] )


class ProfileSeedFromFactsTest( TestCase ):
    """The `create_profile` mapping from session facts to reviewable Profile facts."""

    def _organization( self ) -> Organization:
        return Organization.objects.create( name = 'Org' )

    def test_a_couples_facts_seed_two_reviewable_subjects( self ):
        profile = load_profile( create_profile( self._organization(), _couple_facts() ) )
        self.assertEqual( [ subject.handle for subject in profile.subjects ],
                          [ PRIMARY_SUBJECT_HANDLE, PARTNER_SUBJECT_HANDLE ] )
        self.assertEqual( profile.subjects[ 0 ].birthdate, date( 1960, 1, 1 ) )   # first of the birth year
        self.assertEqual( profile.subjects[ 1 ].name, 'Partner' )                 # a placeholder to review
        self.assertEqual( profile.filing_status, FilingStatus.MARRIED_JOINT )     # implied by the household

    def test_the_benefit_seeds_a_government_pension_per_person( self ):
        profile   = load_profile( create_profile( self._organization(), _couple_facts() ) )
        by_handle = { entitlement.subject_handle: entitlement.monthly_at_normal_age
                      for entitlement in profile.government_pension }
        self.assertEqual( by_handle[ PRIMARY_SUBJECT_HANDLE ], Decimal( '3000' ) )
        self.assertEqual( by_handle[ PARTNER_SUBJECT_HANDLE ], Decimal( '1200' ) )

    def test_a_single_person_without_a_benefit_seeds_one_subject_and_no_pension( self ):
        facts   = SessionFacts( people = [ PersonFacts( birth_year = 1970 ) ] )
        profile = load_profile( create_profile( self._organization(), facts ) )
        self.assertEqual( len( profile.subjects ), 1 )
        self.assertEqual( profile.filing_status, FilingStatus.SINGLE )
        self.assertEqual( profile.government_pension, [] )                         # no benefit -> none seeded

    def test_empty_facts_seed_an_empty_profile( self ):
        profile = load_profile( create_profile( self._organization(), SessionFacts() ) )
        self.assertEqual( profile, Profile() )

    def test_no_facts_still_mint_an_empty_profile( self ):
        profile = load_profile( create_profile( self._organization() ) )           # the pre-5b call form
        self.assertEqual( profile, Profile() )


class MintProfileThreadsSessionFactsTest( TestCase ):
    """`_mint_profile` reads the request's session facts and seeds the household's first profile with them
    -- the wiring the interview and run mint sites share."""

    def _request_with_facts( self, facts : SessionFacts ):
        request = RequestFactory().get( '/inputs/interview/subjects/' )
        request.organization  = Organization.objects.create( name = 'Org' )
        request.session_state = SessionState( session_facts = facts )
        return request

    def test_the_first_profile_is_seeded_from_the_session_facts( self ):
        facts   = SessionFacts( people = [ PersonFacts(
            birth_year = 1961, government_pension_monthly = Decimal( '2500' ), life_expectancy = 87 ) ] )
        profile = load_profile( _mint_profile( self._request_with_facts( facts ) ) )
        self.assertEqual( profile.subjects[ 0 ].birthdate, date( 1961, 1, 1 ) )
        self.assertEqual( profile.government_pension[ 0 ].monthly_at_normal_age, Decimal( '2500' ) )

    def test_no_session_facts_mint_an_empty_profile( self ):
        profile = load_profile( _mint_profile( self._request_with_facts( SessionFacts() ) ) )
        self.assertEqual( profile, Profile() )
