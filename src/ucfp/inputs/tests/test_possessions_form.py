"""PossessionsForm: possession handles are stable across edits, and vehicles are not a possession type.

Plans reference a possession by its handle (a sale event, a vehicle plan's `replaces_vehicle`), so the
handle must survive an edit rather than being reindexed by position -- removing one possession must not
renumber the others. New possessions mint the lowest free `possession-N`, mirroring the debts form.
Vehicles are their own Profile section now (see `vehicle_profile`), so the type choices here are the
minor tangibles only -- precious metals and collectibles.

The lines are a rowset: `possession_type` / `possession_name` / `possession_value` / `possession_handle`
posted as parallel lists, one entry per row, added and removed client-side -- so a removed row is simply
absent from the post (no per-row remove flag).
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.properties import PossessionsForm


def _apply( profile : Profile, *, types = (), names = (), values = (), handles = () ) -> Profile:
    data = QueryDict( mutable = True )
    data.setlist( 'possession_type', list( types ) )
    data.setlist( 'possession_name', list( names ) )
    data.setlist( 'possession_value', list( values ) )
    data.setlist( 'possession_handle', list( handles ) )
    form = PossessionsForm( data, profile = profile, plans = Plans() )
    assert form.is_valid(), form.errors
    result, _plans = form.apply( profile, Plans() )
    return result


def _possession( handle : str, name : str, asset_class : AssetClass, value : str ) -> AssetProfile:
    return AssetProfile( handle = handle, name = name, asset_class = asset_class,
                         opening_value = Decimal( value ) )


class PossessionsFormTests( unittest.TestCase ):

    def test_a_new_possession_mints_a_stable_handle( self ):
        # Adding one line to a fresh profile mints possession-1 and keeps the entered facts.
        result = _apply( Profile(), types = [ 'COLLECTIBLES' ], names = [ 'Ring' ],
                         values = [ '5,000' ], handles = [ '' ] )
        self.assertEqual( len( result.assets ), 1 )
        ring = result.assets[ 0 ]
        self.assertEqual( ring.handle, 'possession-1' )
        self.assertEqual( ring.asset_class, AssetClass.COLLECTIBLES )
        self.assertEqual( ring.opening_value, Decimal( '5000' ) )

    def test_removing_a_possession_keeps_the_others_handles_stable( self ):
        # The first possession's row is dropped (absent from the post); the second must stay possession-2
        # (positional minting would have renumbered it to possession-1) -- the invariant Plans depend on.
        profile = Profile( assets = [
            _possession( 'possession-1', 'Bullion', AssetClass.PRECIOUS_METALS, '30000' ),
            _possession( 'possession-2', 'Ring', AssetClass.COLLECTIBLES, '5000' ) ] )
        result = _apply(
            profile, types = [ 'COLLECTIBLES' ], names = [ 'Ring' ], values = [ '5,000' ],
            handles = [ 'possession-2' ] )
        self.assertEqual( [ asset.handle for asset in result.assets ], [ 'possession-2' ] )

    def test_a_new_possession_alongside_existing_ones_gets_a_free_handle( self ):
        # Keeping possession-1 and adding a second row mints possession-2, never colliding with the kept one.
        profile = Profile( assets = [
            _possession( 'possession-1', 'Bullion', AssetClass.PRECIOUS_METALS, '30000' ) ] )
        result = _apply(
            profile,
            types   = [ 'PRECIOUS_METALS', 'COLLECTIBLES' ],
            names   = [ 'Bullion', 'Ring' ],
            values  = [ '30,000', '5,000' ],
            handles = [ 'possession-1', '' ] )
        self.assertEqual( [ asset.handle for asset in result.assets ], [ 'possession-1', 'possession-2' ] )

    def test_vehicles_are_not_a_possession_type( self ):
        # Vehicles moved to their own section, so DEPRECIATING is no longer an offered type here and a
        # DEPRECIATING holding is left untouched by the possessions form (not renumbered or dropped).
        types = dict( PossessionsForm( profile = Profile() ).type_choices )
        self.assertNotIn( AssetClass.DEPRECIATING.name, types )
        profile = Profile( assets = [
            _possession( 'vehicle-1', 'Car', AssetClass.DEPRECIATING, '30000' ) ] )
        result = _apply( profile, types = [ 'COLLECTIBLES' ], names = [ 'Ring' ],
                         values = [ '5,000' ], handles = [ '' ] )
        self.assertIn( 'vehicle-1', [ asset.handle for asset in result.assets ] )

    def test_a_new_possession_avoids_a_handle_a_transition_asset_still_holds( self ):
        # Pre-split transition data: a DEPRECIATING asset still occupies possession-1. Minting saw only
        # precious-metals/collectibles, so it re-minted possession-1 onto it -- a collision that 500s at
        # book persistence (#146). A new possession must skip to possession-2, past the retained asset.
        profile = Profile( assets = [
            _possession( 'possession-1', '2009 Honda Civic', AssetClass.DEPRECIATING, '20000' ) ] )
        result  = _apply( profile, types = [ 'COLLECTIBLES' ], names = [ 'Coins' ],
                          values = [ '5,000' ], handles = [ '' ] )
        self.assertIn( 'possession-1', [ asset.handle for asset in result.assets ] )   # the asset is kept...
        coins = next( asset for asset in result.assets if asset.name == 'Coins' )
        self.assertEqual( coins.handle, 'possession-2' )                               # ...and not collided

    def test_a_new_possession_skips_both_an_existing_row_and_a_transition_asset( self ):
        # The bug report's shape: an existing collectible on possession-2 AND a transition DEPRECIATING
        # asset on possession-1. A new possession must skip both occupied handles -> possession-3.
        profile = Profile( assets = [
            _possession( 'possession-1', 'Civic', AssetClass.DEPRECIATING, '20000' ),
            _possession( 'possession-2', 'Bullion', AssetClass.PRECIOUS_METALS, '30000' ) ] )
        result  = _apply(
            profile,
            types   = [ 'PRECIOUS_METALS', 'COLLECTIBLES' ],
            names   = [ 'Bullion', 'Coins' ],
            values  = [ '30,000', '5,000' ],
            handles = [ 'possession-2', '' ] )
        self.assertIn( 'possession-1', [ asset.handle for asset in result.assets ] )   # transition kept
        coins = next( asset for asset in result.assets if asset.name == 'Coins' )
        self.assertEqual( coins.handle, 'possession-3' )                               # skips both occupied


if __name__ == '__main__':
    unittest.main()
