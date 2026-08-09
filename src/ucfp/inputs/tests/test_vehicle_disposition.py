"""VehicleDispositionForm: a current vehicle's disposition round-trips, defaulting to Retain.

The value earning a test here is the per-vehicle disposition write (mirroring the Debt plan's per-debt
repayment): Retain is the default and stored as absence; Sell records a dated sale; Replace records a
dated sale plus a successor purchase carrying the current vehicle's name; editing pre-fills; and one
vehicle's edit leaves the others' dispositions intact. The list summary and the materialization are
covered elsewhere (this pins the input write).
"""
import unittest
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string

from common.dataclass_json import from_json_data, to_json_data

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.enums import LeaseDispositionKind, PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LeasedVehicleDisposition, Plans, Vehicle, VehicleDisposition, VehiclePlan )
from ucfp.inputs.profile.schemas import AssetProfile, LeasedVehicle, Profile
from ucfp.inputs.vehicle_disposition import (
    LeasedVehicleDispositionForm, VehicleDispositionForm, all_dispositions_context, dispositions_context,
    leased_dispositions_context )


def _profile( *vehicles ) -> Profile:
    """A profile whose current vehicles are the given (handle, name) DEPRECIATING holdings."""
    return Profile( assets = [
        AssetProfile( handle = h, name = n, asset_class = AssetClass.DEPRECIATING,
                      opening_value = Decimal( '20000' ) )
        for h, n in vehicles ] )


def _apply( profile, plans, handle, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = VehicleDispositionForm( data, profile = profile, plans = plans, handle = handle )
    assert form.is_valid(), form.errors
    _profile, plans = form.apply( profile, plans )
    return plans


def _dispositions( plans ) -> list:
    return plans.vehicle_plan.dispositions if plans.vehicle_plan is not None else []


class VehicleDispositionFormTests( unittest.TestCase ):

    def test_a_fresh_vehicle_defaults_to_retain( self ):
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Sedan' ) ),
                                       plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'kind' ], VehicleDispositionKind.KEEP.name )

    def test_a_sell_records_a_dated_sale( self ):
        plans = _apply( _profile( ( 'vehicle-1', 'Sedan' ) ), Plans(), 'vehicle-1',
                        kind = 'SELL', sale_date = '2032-06-01' )
        self.assertEqual( len( _dispositions( plans ) ), 1 )
        disposition = _dispositions( plans )[ 0 ]
        self.assertEqual( disposition.vehicle_handle, 'vehicle-1' )
        self.assertIs( disposition.kind, VehicleDispositionKind.SELL )
        self.assertEqual( ( disposition.sale_date.year, disposition.sale_date.month ), ( 2032, 6 ) )
        self.assertIsNone( disposition.replacement )              # no successor for a sell

    def test_a_replace_records_a_successor_carrying_the_current_name( self ):
        plans = _apply( _profile( ( 'vehicle-1', 'Old Sedan' ) ), Plans(), 'vehicle-1',
                        kind = 'REPLACE', sale_date = '2032-06-01', purchase_price = '40,000',
                        recurrence_years = '8', payment_method = 'CASH' )
        disposition = _dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, VehicleDispositionKind.REPLACE )
        self.assertIsNotNone( disposition.replacement )
        replacement = disposition.replacement
        self.assertEqual( replacement.name, 'Old Sedan' )         # the successor carries the current name
        self.assertEqual( replacement.purchase_price, Decimal( '40000' ) )
        self.assertEqual( replacement.recurrence_years, 8 )
        self.assertIs( replacement.payment_method, PaymentMethod.CASH )
        self.assertIsNone( replacement.purchase_date )            # supplied at materialization from `date`

    def test_retain_clears_any_stored_disposition( self ):
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL ) ] ) )
        plans = _apply( _profile( ( 'vehicle-1', 'Sedan' ) ), existing, 'vehicle-1', kind = 'KEEP' )
        self.assertEqual( _dispositions( plans ), [] )            # collapses back to the default (absence)

    def test_editing_one_vehicle_leaves_the_others_disposition_intact( self ):
        other    = VehicleDisposition( vehicle_handle = 'vehicle-2', kind = VehicleDispositionKind.SELL )
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [ other ] ) )
        profile  = _profile( ( 'vehicle-1', 'Sedan' ), ( 'vehicle-2', 'Truck' ) )
        plans    = _apply( profile, existing, 'vehicle-1', kind = 'SELL', sale_date = '2033-01-01' )
        handles  = { d.vehicle_handle for d in _dispositions( plans ) }
        self.assertEqual( handles, { 'vehicle-1', 'vehicle-2' } )

    def test_edit_pre_fills_from_a_stored_replacement( self ):
        car      = Vehicle( handle = '', name = 'Old Sedan', purchase_price = Decimal( '40000' ),
                            recurrence_years = 8, payment_method = PaymentMethod.LOAN,
                            down_payment = Decimal( '9000' ) )
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                replacement = car ) ] ) )
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Old Sedan' ) ),
                                       plans = existing, handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'kind' ], VehicleDispositionKind.REPLACE.name )
        self.assertEqual( form.initial[ 'purchase_price' ], Decimal( '40000' ) )
        self.assertEqual( form.initial[ 'payment_method' ], PaymentMethod.LOAN.name )
        self.assertEqual( form.initial[ 'down_payment' ], Decimal( '9000' ) )


class DispositionListTests( unittest.TestCase ):
    """The list shows every current vehicle -- Retain when none is stored, else the stored kind summarized
    with the year it happens."""

    def test_lists_current_vehicles_with_summaries( self ):
        profile  = _profile( ( 'vehicle-1', 'Sedan' ), ( 'vehicle-2', 'Truck' ) )
        plans    = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2032, 6, 1 ) ) ] ) )
        rows = dispositions_context( profile, plans )
        self.assertEqual( [ r[ 'name' ] for r in rows ], [ 'Sedan', 'Truck' ] )
        self.assertEqual( rows[ 0 ][ 'summary' ], 'Sell in 2032' )
        self.assertEqual( rows[ 1 ][ 'summary' ], 'Retain' )      # no stored disposition -> the default

    def test_combines_owned_and_leased_with_ownership_and_edit_route( self ):
        # The one list carries both kinds -- owned then leased -- each tagged with the editor its Edit opens.
        profile = Profile(
            assets = [ AssetProfile( handle = 'vehicle-1', name = 'Sedan',
                                     asset_class = AssetClass.DEPRECIATING,
                                     opening_value = Decimal( '20000' ) ) ],
            leased_vehicles = [ LeasedVehicle( handle = 'vehicle-2', name = 'Truck' ) ] )
        rows = all_dispositions_context( profile, Plans() )
        self.assertEqual( [ ( r[ 'name' ], r[ 'ownership' ], r[ 'edit_route' ] ) for r in rows ],
                          [ ( 'Sedan', 'Owned', 'vehicle_disposition_edit' ),
                            ( 'Truck', 'Leased', 'leased_disposition_edit' ) ] )


def _leased_profile( *vehicles ) -> Profile:
    return Profile( leased_vehicles = [ LeasedVehicle( handle = h, name = n ) for h, n in vehicles ] )


def _leased_apply( profile, plans, handle, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = LeasedVehicleDispositionForm( data, profile = profile, plans = plans, handle = handle )
    assert form.is_valid(), form.errors
    _profile, plans = form.apply( profile, plans )
    return plans


def _leased_dispositions( plans ) -> list:
    return plans.vehicle_plan.leased_dispositions if plans.vehicle_plan is not None else []


class LeasedDispositionFormTests( unittest.TestCase ):

    def test_a_fresh_lease_defaults_to_return( self ):
        form = LeasedVehicleDispositionForm( profile = _leased_profile( ( 'lease-1', 'Sedan' ) ),
                                             plans = Plans(), handle = 'lease-1' )
        self.assertEqual( form.initial[ 'kind' ], LeaseDispositionKind.RETURN.name )

    def test_a_bare_return_stores_nothing( self ):
        # Return with no terms is the default -- stored as absence, so the plan stays empty.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RETURN' )
        self.assertEqual( _leased_dispositions( plans ), [] )

    def test_a_return_with_terms_records_the_current_lease( self ):
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RETURN', monthly = '400', lease_end = '2029-01-01' )
        disposition = _leased_dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, LeaseDispositionKind.RETURN )
        self.assertEqual( disposition.monthly, Decimal( '400' ) )
        self.assertEqual( disposition.lease_end, date( 2029, 1, 1 ) )
        self.assertIsNone( disposition.successor )

    def test_a_buy_with_cash_records_a_cash_successor_carrying_the_lease_name( self ):
        # The kind fixes the successor's payment method -- no payment field is submitted.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Leased Sedan' ) ), Plans(), 'lease-1',
                               kind = 'BUY_CASH', monthly = '400', lease_end = '2029-01-01',
                               purchase_price = '30,000', recurrence_years = '7' )
        disposition = _leased_dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, LeaseDispositionKind.BUY_CASH )
        self.assertEqual( disposition.successor.name, 'Leased Sedan' )
        self.assertEqual( disposition.successor.purchase_price, Decimal( '30000' ) )
        self.assertIs( disposition.successor.payment_method, PaymentMethod.CASH )
        self.assertIsNone( disposition.successor.purchase_date )     # supplied at materialization

    def test_a_renew_records_a_lease_successor( self ):
        # Renew implies the lease payment type -- its successor is a LEASE, from the kind, not a picker.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RENEW', monthly = '400', lease_end = '2029-01-01',
                               monthly_payment = '450', recurrence_years = '3' )
        successor = _leased_dispositions( plans )[ 0 ].successor
        self.assertIs( successor.payment_method, PaymentMethod.LEASE )
        self.assertEqual( successor.monthly_payment, Decimal( '450' ) )

    def test_edit_pre_fills_the_current_lease_and_kind( self ):
        existing = Plans( vehicle_plan = VehiclePlan( leased_dispositions = [
            LeasedVehicleDisposition(
                vehicle_handle = 'lease-1', monthly = Decimal( '350' ), lease_end = date( 2028, 6, 1 ),
                kind = LeaseDispositionKind.RENEW ) ] ) )
        form = LeasedVehicleDispositionForm( profile = _leased_profile( ( 'lease-1', 'Sedan' ) ),
                                             plans = existing, handle = 'lease-1' )
        self.assertEqual( form.initial[ 'kind' ], LeaseDispositionKind.RENEW.name )
        self.assertEqual( form.initial[ 'monthly' ], Decimal( '350' ) )
        self.assertEqual( form.initial[ 'lease_end' ], date( 2028, 6, 1 ) )

    def test_the_list_summarizes_each_leased_vehicle( self ):
        profile = _leased_profile( ( 'lease-1', 'Sedan' ), ( 'lease-2', 'Truck' ) )
        plans   = Plans( vehicle_plan = VehiclePlan( leased_dispositions = [
            LeasedVehicleDisposition( vehicle_handle = 'lease-1', kind = LeaseDispositionKind.BUY_CASH,
                                      lease_end = date( 2029, 1, 1 ) ) ] ) )
        rows = leased_dispositions_context( profile, plans )
        self.assertEqual( rows[ 0 ][ 'summary' ], 'Buy with cash in 2029' )
        self.assertEqual( rows[ 1 ][ 'summary' ], 'Return' )        # no stored disposition -> the default


class DispositionSerializationTests( unittest.TestCase ):
    """A disposition round-trips through the JSON codec with its date intact -- the regression for the
    field once named `date`, which shadowed the `date` type when annotations were resolved and left the
    stored value an un-parsed string (crashing anything that used it as a date)."""

    def test_a_dated_disposition_round_trips_as_a_date( self ):
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2032, 6, 1 ) ) ] ) )
        restored = from_json_data( Plans, to_json_data( plans ) )
        self.assertEqual( restored, plans )
        self.assertIsInstance( restored.vehicle_plan.dispositions[ 0 ].sale_date, date )

    def test_a_replace_disposition_with_a_successor_round_trips( self ):
        car   = Vehicle( handle = '', name = 'Sedan', purchase_price = Decimal( '40000' ),
                         recurrence_years = 8, payment_method = PaymentMethod.LOAN )
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                sale_date = date( 2032, 6, 1 ), replacement = car ) ] ) )
        self.assertEqual( from_json_data( Plans, to_json_data( plans ) ), plans )


class DispositionFormRenderTests( unittest.TestCase ):
    """The editor template renders, wiring the kind switch (revealing the date and the replacement) and,
    nested within the replacement, the payment switch -- the one server-side contract a JS test can't cover
    (that both switches' case values reach the markup)."""

    def _render( self ):
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Sedan' ) ),
                                       plans = Plans(), handle = 'vehicle-1' )
        html = render_to_string(
            'inputs/interview/sections/vehicle_disposition_form.html',
            { 'disposition_form': form, 'handle': 'vehicle-1', 'AppConst': AppConst } )
        return form, html

    def test_both_switches_case_values_render( self ):
        form, html = self._render()
        attr = f'data-{AppConst.SWITCH_CASE_DATA_ATTR}'
        self.assertIn( f'{attr}="{form.dated_kinds}"', html )               # kind switch: the date
        self.assertIn( f'{attr}="{form.replace_kind}"', html )             # kind switch: the replacement
        self.assertIn( f'{attr}="{form.payment_field_methods}"', html )    # nested payment switch


if __name__ == '__main__':
    unittest.main()
