"""Rental tenant-paid utilities default to $0 (#186).

A landlord's tenant, not the landlord, ordinarily pays the utilities (water, trash, electric, gas,
phone, internet), so a rental should not carry the residence utility amounts out of the box. The catalog
marks those rows `tenant_paid`, and the property-expenses merge seeds a $0 override for each rental on
them -- while a residence keeps its normal defaults, a second home (owner-occupied) is untouched, and
landlord-borne items (tax, insurance, management, maintenance, structural) keep their defaults for every
property. The user can still raise a cell for a utilities-included rental.
"""
from dataclasses import replace
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.expenses import ordered_catalog
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.property_expenses import merged_property_expenses

RESIDENCE = AssetClass.REAL_ESTATE_RESIDENCE
RENTAL    = AssetClass.REAL_ESTATE_RENTAL
SECOND    = AssetClass.REAL_ESTATE_SECOND_HOME

TENANT_PAID = ( 'water', 'trash', 'electric', 'gas-utility', 'phone-service', 'internet' )
LANDLORD    = ( 'property-tax', 'property-insurance', 'property-management', 'maintenance-repair',
                'roof-cost' )


def _profile( *properties ) -> Profile:
    """A household owning the given ( handle, asset_class ) properties -- enough for property expenses to
    apply."""
    return Profile( assets = [
        AssetProfile( handle = handle, name = handle, asset_class = asset_class,
                      opening_value = Decimal( '300000' ) )
        for handle, asset_class in properties ] )


class RentalUtilityDefaultsTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    @staticmethod
    def _merged( profile, plans = None ) -> dict:
        return { expense.handle: expense for expense in merged_property_expenses( profile, plans or Plans() ) }

    def test_trash_is_a_tenant_paid_catalog_row( self ):
        trash = next( ( e for e in ordered_catalog() if e.handle == 'trash' ), None )
        self.assertIsNotNone( trash, 'Trash / Garbage row missing from the catalog' )
        self.assertTrue( trash.tenant_paid )
        self.assertEqual( trash.default_amount, Decimal( '35' ) )

    def test_all_six_tenant_paid_utilities_are_flagged( self ):
        flagged = { e.handle for e in ordered_catalog() if e.tenant_paid }
        self.assertEqual( flagged, set( TENANT_PAID ) )

    def test_a_rental_seeds_tenant_paid_utilities_to_zero( self ):
        merged = self._merged( _profile( ( 'rent-1', RENTAL ) ) )
        for handle in TENANT_PAID:
            self.assertEqual( merged[ handle ].overrides.get( 'rent-1' ), Decimal( 0 ),
                              f'{handle} should default to $0 for a rental' )

    def test_a_residence_keeps_its_utility_defaults( self ):
        merged = self._merged( _profile( ( 'res-1', RESIDENCE ) ) )
        for handle in TENANT_PAID:                                     # no override -> inherits the default
            self.assertNotIn( 'res-1', merged[ handle ].overrides,
                              f'{handle} should keep its default for a residence' )

    def test_a_second_home_keeps_its_utility_defaults( self ):
        merged = self._merged( _profile( ( 'home-2', SECOND ) ) )
        for handle in TENANT_PAID:                                     # owner-occupied: not zeroed
            self.assertNotIn( 'home-2', merged[ handle ].overrides )

    def test_landlord_items_are_unaffected_for_a_rental( self ):
        merged = self._merged( _profile( ( 'rent-1', RENTAL ) ) )
        for handle in LANDLORD:
            expense = merged.get( handle )
            if expense is not None:                                    # applies to rentals
                self.assertNotIn( 'rent-1', expense.overrides,
                                  f'{handle} is landlord-borne and must keep its default' )

    def test_a_mixed_household_zeroes_only_the_rental_column( self ):
        merged = self._merged( _profile( ( 'res-1', RESIDENCE ), ( 'rent-1', RENTAL ) ) )
        for handle in TENANT_PAID:
            overrides = merged[ handle ].overrides
            self.assertEqual( overrides.get( 'rent-1' ), Decimal( 0 ) )
            self.assertNotIn( 'res-1', overrides )                     # residence still inherits its default

    def test_a_user_amount_for_a_utilities_included_rental_is_preserved( self ):
        # A landlord who does pay a rental's electric sets it; the merge keeps that, not a re-seeded $0.
        profile = _profile( ( 'rent-1', RENTAL ) )
        electric = next( e for e in merged_property_expenses( profile, Plans() ) if e.handle == 'electric' )
        stored   = replace( electric, overrides = { 'rent-1': Decimal( '120' ) } )
        merged   = self._merged( profile, Plans( property_expenses = [ stored ] ) )
        self.assertEqual( merged[ 'electric' ].overrides[ 'rent-1' ], Decimal( '120' ) )
