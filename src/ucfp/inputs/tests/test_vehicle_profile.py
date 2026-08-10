"""CurrentVehicleForm: one current vehicle -- owned or leased -- in one list.

An owned vehicle materializes as a `DEPRECIATING` holding plus an optional `AUTO` loan; a leased vehicle
as a thin `LeasedVehicle` fact. Both share one handle space, so flipping ownership moves the vehicle
between the two stores under the same handle and drops its now-mismatched vehicle-plan disposition. The
combined list and the delete reap round it out.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.plans.enums import LeaseDispositionKind, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LeasedVehicleDisposition, Plans, VehicleDisposition, VehiclePlan )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, LeasedVehicle, Profile
from ucfp.inputs.vehicle_profile import (
    CurrentVehicleForm, current_vehicles_context, delete_current_vehicle )


def _apply( profile, plans, handle = None, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = CurrentVehicleForm( data, profile = profile, plans = plans, handle = handle )
    assert form.is_valid(), form.errors
    return form.apply( profile, plans )


def _owned( handle, name, value = '30000' ) -> AssetProfile:
    return AssetProfile( handle = handle, name = name, asset_class = AssetClass.DEPRECIATING,
                         opening_value = Decimal( value ) )


def _loan( vehicle_handle = 'vehicle-1' ) -> Debt:
    return Debt( handle = f'{vehicle_handle}-loan', name = 'Loan', kind = DebtKind.AUTO,
                 balance = Decimal( '18000' ), secured_asset = vehicle_handle )


def _owned_disposition( plans_handle = 'vehicle-1' ) -> Plans:
    return Plans( vehicle_plan = VehiclePlan( dispositions = [
        VehicleDisposition( vehicle_handle = plans_handle, kind = VehicleDispositionKind.SELL ) ] ) )


def _leased_disposition( plans_handle = 'vehicle-1' ) -> Plans:
    return Plans( vehicle_plan = VehiclePlan( leased_dispositions = [
        LeasedVehicleDisposition( vehicle_handle = plans_handle, kind = LeaseDispositionKind.RENEW ) ] ) )


class OwnedVehicleTests( unittest.TestCase ):

    def test_owned_writes_a_depreciating_holding( self ):
        profile, _plans = _apply( Profile(), Plans(), name = 'Car', ownership = 'owned', value = '30,000' )
        self.assertEqual( len( profile.assets ), 1 )
        car = profile.assets[ 0 ]
        self.assertEqual( car.handle, 'vehicle-1' )                 # minted
        self.assertEqual( car.asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( car.opening_value, Decimal( '30000' ) )
        self.assertEqual( profile.debts, [] )                      # no balance -> no loan

    def test_a_loan_balance_creates_a_secured_auto_loan( self ):
        profile, _plans = _apply( Profile(), Plans(), handle = 'vehicle-1', name = 'Car',
                                  ownership = 'owned', value = '30,000', loan_balance = '18,000' )
        loan = profile.debts[ 0 ]
        self.assertEqual( ( loan.handle, loan.kind, loan.secured_asset ),
                          ( 'vehicle-1-loan', DebtKind.AUTO, 'vehicle-1' ) )

    def test_owned_without_a_value_writes_nothing( self ):
        profile, _plans = _apply( Profile(), Plans(), name = 'Car', ownership = 'owned' )
        self.assertEqual( profile.assets, [] )

    def test_owned_pre_fills_on_edit( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ], debts = [ _loan() ] )
        form = CurrentVehicleForm( profile = profile, plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'ownership' ], 'owned' )
        self.assertEqual( form.initial[ 'value' ], Decimal( '30000' ) )
        self.assertEqual( form.initial[ 'loan_balance' ], Decimal( '18000' ) )


class LeasedVehicleTests( unittest.TestCase ):

    def test_leased_writes_a_lease_fact_and_no_asset( self ):
        profile, _plans = _apply( Profile(), Plans(), name = 'Leased Car', ownership = 'leased' )
        self.assertEqual( [ ( v.handle, v.name ) for v in profile.leased_vehicles ],
                          [ ( 'vehicle-1', 'Leased Car' ) ] )
        self.assertEqual( profile.assets, [] )

    def test_leased_pre_fills_on_edit( self ):
        profile = Profile( leased_vehicles = [ LeasedVehicle( 'vehicle-1', 'Leased Car' ) ] )
        form = CurrentVehicleForm( profile = profile, plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'ownership' ], 'leased' )
        self.assertEqual( form.initial[ 'name' ], 'Leased Car' )

    def test_a_handle_is_minted_free_across_owned_and_leased( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ],
                           leased_vehicles = [ LeasedVehicle( 'vehicle-2', 'Lease' ) ] )
        profile, _plans = _apply( profile, Plans(), name = 'New Lease', ownership = 'leased' )
        self.assertIn( 'vehicle-3', [ v.handle for v in profile.leased_vehicles ] )


class OwnershipToggleTests( unittest.TestCase ):
    """Flipping ownership on an existing vehicle moves it between stores under the same handle; a
    now-mismatched disposition is left for on-demand reconciliation, not dropped here. An edit that keeps
    the type keeps the disposition."""

    def test_owned_to_leased_moves_stores_leaving_the_owned_disposition( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ], debts = [ _loan() ] )
        profile, plans = _apply( profile, _owned_disposition(), handle = 'vehicle-1', name = 'Car',
                                 ownership = 'leased' )
        self.assertEqual( [ v.handle for v in profile.leased_vehicles ], [ 'vehicle-1' ] )
        self.assertEqual( ( profile.assets, profile.debts ), ( [], [] ) )      # the loan went with it
        # The now-mismatched owned disposition is left as drift (reconciled on demand), not reaped here.
        self.assertEqual( [ d.vehicle_handle for d in plans.vehicle_plan.dispositions ], [ 'vehicle-1' ] )

    def test_leased_to_owned_moves_stores_leaving_the_leased_disposition( self ):
        profile = Profile( leased_vehicles = [ LeasedVehicle( 'vehicle-1', 'Car' ) ] )
        profile, plans = _apply( profile, _leased_disposition(), handle = 'vehicle-1', name = 'Car',
                                 ownership = 'owned', value = '25,000' )
        self.assertEqual( [ a.handle for a in profile.assets ], [ 'vehicle-1' ] )
        self.assertEqual( profile.leased_vehicles, [] )
        self.assertEqual(
            [ d.vehicle_handle for d in plans.vehicle_plan.leased_dispositions ], [ 'vehicle-1' ] )

    def test_editing_without_flipping_keeps_the_disposition( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ] )
        profile, plans = _apply( profile, _owned_disposition(), handle = 'vehicle-1', name = 'Car',
                                 ownership = 'owned', value = '31,000' )
        self.assertEqual( len( plans.vehicle_plan.dispositions ), 1 )          # same type -> kept


class CombinedListTests( unittest.TestCase ):

    def test_lists_owned_then_leased_with_ownership( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ],
                           leased_vehicles = [ LeasedVehicle( 'vehicle-2', 'Lease' ) ] )
        rows = current_vehicles_context( profile )
        self.assertEqual( [ ( r[ 'name' ], r[ 'ownership' ] ) for r in rows ],
                          [ ( 'Car', 'Owned' ), ( 'Lease', 'Leased' ) ] )

    def test_deleting_an_owned_vehicle_removes_it_and_its_loan( self ):
        profile = Profile( assets = [ _owned( 'vehicle-1', 'Car' ) ], debts = [ _loan() ] )
        profile, plans = delete_current_vehicle( profile, _owned_disposition(), 'vehicle-1' )
        self.assertEqual( ( profile.assets, profile.debts ), ( [], [] ) )
        # The disposition is left as drift (reconciled on demand), not reaped on delete.
        self.assertEqual( [ d.vehicle_handle for d in plans.vehicle_plan.dispositions ], [ 'vehicle-1' ] )

    def test_deleting_a_leased_vehicle_removes_it( self ):
        profile = Profile( leased_vehicles = [ LeasedVehicle( 'vehicle-1', 'Lease' ) ] )
        profile, plans = delete_current_vehicle( profile, _leased_disposition(), 'vehicle-1' )
        self.assertEqual( profile.leased_vehicles, [] )
        self.assertEqual(
            [ d.vehicle_handle for d in plans.vehicle_plan.leased_dispositions ], [ 'vehicle-1' ] )


if __name__ == '__main__':
    unittest.main()
