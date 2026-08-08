"""PossessionsForm: possession handles are stable across edits, and the type is "Vehicle".

Plans reference a possession by its handle (a sale event, a vehicle plan's `replaces_possession`), so the
handle must survive an edit rather than being reindexed by position -- removing one possession must not
renumber the others. New possessions mint the lowest free `possession-N`, mirroring the debts form.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.properties import PossessionsForm


def _apply( profile : Profile, **fields ) -> Profile:
    data = QueryDict( mutable = True )
    data.update( fields )
    form = PossessionsForm( data, profile = profile, plans = Plans() )
    assert form.is_valid(), form.errors
    result, _plans = form.apply( profile, Plans() )
    return result


def _possession( handle : str, name : str, asset_class : AssetClass, value : str ) -> AssetProfile:
    return AssetProfile( handle = handle, name = name, asset_class = asset_class,
                         opening_value = Decimal( value ) )


class PossessionsFormTests( unittest.TestCase ):

    def test_a_new_possession_mints_a_stable_handle( self ):
        # A fresh profile has one blank row; filling it mints possession-1 and keeps the entered facts.
        result = _apply( Profile(), name_0 = 'Car', value_0 = '30,000', type_0 = 'DEPRECIATING' )
        self.assertEqual( len( result.assets ), 1 )
        car = result.assets[ 0 ]
        self.assertEqual( car.handle, 'possession-1' )
        self.assertEqual( car.asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( car.opening_value, Decimal( '30000' ) )

    def test_removing_a_possession_keeps_the_others_handles_stable( self ):
        # Remove the first possession; the second must stay possession-2 (positional minting would have
        # renumbered it to possession-1) -- the invariant Plans references depend on.
        profile = Profile( assets = [
            _possession( 'possession-1', 'Car', AssetClass.DEPRECIATING, '30000' ),
            _possession( 'possession-2', 'Ring', AssetClass.COLLECTIBLES, '5000' ) ] )
        result = _apply(
            profile,
            handle_0 = 'possession-1', name_0 = 'Car', value_0 = '30,000', type_0 = 'DEPRECIATING',
            remove_0 = 'on',
            handle_1 = 'possession-2', name_1 = 'Ring', value_1 = '5,000', type_1 = 'COLLECTIBLES' )
        self.assertEqual( [ asset.handle for asset in result.assets ], [ 'possession-2' ] )

    def test_a_new_possession_alongside_existing_ones_gets_a_free_handle( self ):
        # Keeping possession-1 and adding a second row mints possession-2, never colliding with the kept one.
        profile = Profile( assets = [
            _possession( 'possession-1', 'Car', AssetClass.DEPRECIATING, '30000' ) ] )
        result = _apply(
            profile,
            handle_0 = 'possession-1', name_0 = 'Car', value_0 = '30,000', type_0 = 'DEPRECIATING',
            name_1 = 'Ring', value_1 = '5,000', type_1 = 'COLLECTIBLES' )
        self.assertEqual( [ asset.handle for asset in result.assets ], [ 'possession-1', 'possession-2' ] )

    def test_the_depreciating_type_is_labelled_vehicle( self ):
        labels = dict( PossessionsForm( profile = Profile() ).fields[ 'type_0' ].choices )
        self.assertEqual( labels[ AssetClass.DEPRECIATING.name ], 'Vehicle' )
        self.assertNotIn( 'Vehicle or boat', labels.values() )


if __name__ == '__main__':
    unittest.main()
