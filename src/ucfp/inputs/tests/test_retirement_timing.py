"""RetirementForm: the per-subject expected lifetime is entered as an *age only* (no paired date, unlike
the SS/pension elections) and stored as the age-derived date the engine's survivor transition reads. Blank
= not modeled; a stored date pre-fills the age.
"""
import unittest
from datetime import date

from django.http import QueryDict

from ucfp.inputs.plans.schemas import Plans, RetirementTiming
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.retirement import RetirementForm


def _profile() -> Profile:
    return Profile( subjects = [ SubjectProfile( handle = 'you', name = 'You',
                                                 birthdate = date( 1960, 1, 1 ) ) ] )


def _post( **fields ) -> QueryDict:
    data = QueryDict( mutable = True )
    for name, value in fields.items():
        data[ name ] = value
    return data


class ExpectedLifetimeTests( unittest.TestCase ):

    def _apply( self, **fields ):
        form = RetirementForm( _post( **fields ), profile = _profile(), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( _profile(), Plans() )
        return plans.timing[ 0 ]

    def test_an_age_stores_the_age_derived_date( self ):
        # Age-only: 90 for someone born 1960 -> the date they turn 90.
        timing = self._apply( s0_life_age = '90' )
        self.assertEqual( timing.subject_handle, 'you' )
        self.assertEqual( timing.expected_lifetime, date( 2050, 1, 1 ) )

    def test_a_blank_lifetime_is_not_modeled( self ):
        self.assertIsNone( self._apply().expected_lifetime )

    def test_a_stored_lifetime_prefills_the_age( self ):
        plans = Plans( timing = [ RetirementTiming(
            subject_handle = 'you', expected_lifetime = date( 2050, 1, 1 ) ) ] )
        form = RetirementForm( profile = _profile(), plans = plans )
        self.assertEqual( form.subject_groups[ 0 ][ 'lifetime' ].value(), 90 )   # derived from the date

    def test_all_three_elections_land_together( self ):
        # ss / pension / lifetime all write onto one RetirementTiming via `replace`; submitting them
        # together guards against one election clobbering another.
        timing = self._apply( s0_ss_from = '2027-01', s0_pen_from = '2025-06', s0_life_age = '90' )
        self.assertEqual( timing.government_pension_claiming_date, date( 2027, 1, 15 ) )
        self.assertEqual( timing.pension_start, date( 2025, 6, 15 ) )
        self.assertEqual( timing.expected_lifetime, date( 2050, 1, 1 ) )

    def test_an_implausible_age_is_rejected( self ):
        form = RetirementForm( _post( s0_life_age = '121' ), profile = _profile(), plans = Plans() )
        self.assertFalse( form.is_valid() )                  # the field's max_value = 120
