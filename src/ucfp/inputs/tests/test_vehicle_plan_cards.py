"""The Vehicle plan's one card list and the Vehicle expenses empty state (Phase 2 of the interview-UI pass).

The value pinned here is the structural twist between the two vehicle kinds sharing one list: a *current*
vehicle is a Vehicles/Profile fact, so its card carries Edit (to set its plan) but no Remove and a
"From Profile" note, while a *future* vehicle carries both Edit and Remove. This is the contract the
input-item-card Edit/Remove decoupling exists to express. Also pinned: with no vehicles, the Vehicle
expenses step points back to the Vehicle plan instead of showing the per-vehicle running-costs table.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.template.loader import render_to_string

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.interview import VehicleExpensesSectionForm
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import Plans, Vehicle, VehiclePlan
from ucfp.inputs.profile.schemas import AssetProfile, LeasedVehicle, Profile
from ucfp.inputs.vehicle_disposition import current_card_key, future_card_key, vehicle_plan_cards


def _profile_with_current() -> Profile:
    """A profile with one owned current vehicle -- the DEPRECIATING holding the Vehicles section enters."""
    return Profile( assets = [
        AssetProfile( handle = 'vehicle-1', name = 'Sedan', asset_class = AssetClass.DEPRECIATING,
                      opening_value = Decimal( '20000' ) ) ] )


def _plans_with_future() -> Plans:
    """Plans carrying one net-new future vehicle."""
    future = Vehicle( handle = 'vehicle-2', name = 'Truck', purchase_date = date( 2030, 1, 1 ),
                      purchase_price = Decimal( '35000' ), recurrence_years = 7,
                      payment_method = PaymentMethod.CASH )
    return Plans( vehicle_plan = VehiclePlan( vehicles = [ future ] ) )


class VehiclePlanCardsTests( unittest.TestCase ):

    def test_current_vehicles_come_before_future_ones( self ):
        cards = vehicle_plan_cards( _profile_with_current(), _plans_with_future() )
        self.assertEqual( [ c[ 'badge' ] for c in cards ], [ 'Current', 'Future' ] )
        self.assertEqual( [ c[ 'title' ] for c in cards ], [ 'Sedan', 'Truck' ] )

    def test_a_leased_current_vehicle_builds_a_card( self ):
        # A leased current vehicle carries no loan line; the shared card builder must handle its row shape
        # (regression: _current_detail once assumed every current row had a 'loan' key -> KeyError).
        plans = Plans()
        cards = vehicle_plan_cards(
            Profile( leased_vehicles = [ LeasedVehicle( handle = 'vehicle-1', name = 'Leased Car' ) ] ),
            plans )
        self.assertEqual( [ c[ 'badge' ] for c in cards ], [ 'Current' ] )
        self.assertEqual( cards[ 0 ][ 'title' ], 'Leased Car' )

    def test_a_current_vehicle_is_editable_but_not_removable( self ):
        current = vehicle_plan_cards( _profile_with_current(), Plans() )[ 0 ]
        self.assertIsNotNone( current[ 'edit_url' ] )        # Edit sets its plan
        self.assertIsNone( current[ 'delete_url' ] )         # but it is removed in the Profile
        self.assertIsNotNone( current[ 'source_note' ] )     # it points back to where it is entered

    def test_a_future_vehicle_is_fully_managed( self ):
        future = vehicle_plan_cards( Profile(), _plans_with_future() )[ 0 ]
        self.assertIsNotNone( future[ 'edit_url' ] )
        self.assertIsNotNone( future[ 'delete_url' ] )
        self.assertIsNone( future[ 'source_note' ] )

    def test_the_rendered_list_gives_current_edit_only_and_future_both( self ):
        cards = vehicle_plan_cards( _profile_with_current(), _plans_with_future() )
        html  = render_to_string( 'inputs/interview/sections/vehicle_plan_list.html',
                                  { 'cards': cards, 'active': None } )
        self.assertIn( 'aria-label="Edit Sedan"', html )     # both are editable
        self.assertIn( 'aria-label="Edit Truck"', html )
        self.assertEqual( html.count( 'aria-label="Remove' ), 1 )   # only the future card is removable
        self.assertIn( 'aria-label="Remove Truck"', html )

    def test_a_colliding_current_and_future_handle_highlight_independently( self ):
        # Current and future vehicles each mint `vehicle-N` in their own space, so both can be `vehicle-1`.
        # Editing one must highlight only its card -- the kind-scoped active key disambiguates each way, so
        # neither key ever lights both cards.
        colliding = Plans( vehicle_plan = VehiclePlan( vehicles = [
            Vehicle( handle = 'vehicle-1', name = 'Truck', purchase_date = date( 2030, 1, 1 ),
                     purchase_price = Decimal( '35000' ), recurrence_years = 7,
                     payment_method = PaymentMethod.CASH ) ] ) )
        cards = vehicle_plan_cards( _profile_with_current(), colliding )  # current vehicle-1 + future vehicle-1
        for active in ( current_card_key( 'vehicle-1' ), future_card_key( 'vehicle-1' ) ):
            html = render_to_string( 'inputs/interview/sections/vehicle_plan_list.html',
                                     { 'cards': cards, 'active': active } )
            self.assertEqual( html.count( 'input-item-card--active' ), 1 )   # exactly one card, never both


class VehicleExpensesEmptyStateTests( unittest.TestCase ):

    def test_no_vehicles_points_back_to_the_vehicle_plan_step( self ):
        form = VehicleExpensesSectionForm( profile = Profile(), plans = Plans() )
        self.assertFalse( form.has_vehicles )
        html = render_to_string( 'inputs/interview/sections/vehicle_expenses.html', { 'form': form } )
        self.assertNotIn( '<table', html )   # structural: the per-vehicle running-costs table is withheld

    def test_counts_frame_the_running_costs_when_vehicles_exist( self ):
        form = VehicleExpensesSectionForm( profile = _profile_with_current(), plans = _plans_with_future() )
        self.assertTrue( form.has_vehicles )
        self.assertEqual( form.current_count, 1 )
        self.assertEqual( form.future_count, 1 )

    def test_the_scope_phrase_omits_a_zero_count( self ):
        # Behaviour, not copy: a zero count is dropped, never rendered as "0 ...". Asserting on the digit
        # (not the surrounding words) keeps this independent of the note's exact phrasing.
        form = VehicleExpensesSectionForm( profile = _profile_with_current(), plans = Plans() )  # 1, then 0
        self.assertNotIn( '0', form.vehicle_scope_phrase )
