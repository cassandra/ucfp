"""HomeForm's tenure is unset until the household answers the housing question.

The residence radio starts with no selection (a fresh profile has home_tenure=None), so the switch
shows no fields until a choice is made -- soliciting an explicit answer. 'Neither' stays a distinct
explicit choice (no home), separate from the unselected start.
"""
import unittest

from django.http import QueryDict

from ucfp.inputs.interview import HomeForm
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import Profile


def _applied( **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = HomeForm( data, profile = Profile(), plans = Plans() )
    assert form.is_valid(), form.errors
    profile, _plans = form.apply( Profile(), Plans() )
    return profile


class HomeTenureTests( unittest.TestCase ):

    def test_fresh_profile_starts_with_no_tenure( self ):
        self.assertIsNone( Profile().home_tenure )

    def test_blank_tenure_is_valid_and_stays_unset( self ):
        self.assertIsNone( _applied().home_tenure )   # no radio chosen -- not required, holds no tenure

    def test_choosing_own_records_it( self ):
        self.assertIs( _applied( tenure = 'own', home_value = '500,000' ).home_tenure, HousingTenure.OWN )

    def test_neither_is_a_distinct_explicit_answer( self ):
        self.assertIs( _applied( tenure = 'neither' ).home_tenure, HousingTenure.NEITHER )
