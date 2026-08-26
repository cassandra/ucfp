"""RetirementForm: the per-subject expected-lifetime election round-trips into RetirementTiming (blank =
not modeled), alongside the existing Social Security / pension elections. The date is canonical; a JS-less
client that submits only an age falls back to the age-derived date.
"""
import unittest
from datetime import date

from django.http import QueryDict

from ucfp.inputs.plans.schemas import Plans
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

    def test_a_lifetime_date_round_trips_into_the_timing( self ):
        timing = self._apply( s0_life_from = '2050-06-01' )
        self.assertEqual( timing.subject_handle, 'you' )
        self.assertEqual( timing.expected_lifetime, date( 2050, 6, 1 ) )

    def test_a_blank_lifetime_is_not_modeled( self ):
        self.assertIsNone( self._apply().expected_lifetime )

    def test_an_age_with_no_date_falls_back_to_the_derived_date( self ):
        # JS-less client: an age with a blank date resolves to birthdate + age (1960 + 90).
        self.assertEqual( self._apply( s0_life_from_age = '90' ).expected_lifetime, date( 2050, 1, 1 ) )
