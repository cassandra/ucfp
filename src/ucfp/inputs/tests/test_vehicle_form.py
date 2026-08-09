"""VehicleForm: the payment method round-trips through the form and drives the derived Vehicle.

The method radio is not required (a blank submit falls back to cash), the per-method payment fields are
carried onto the `Vehicle`, and an existing vehicle's method pre-fills on edit. The form also surfaces the
assumed auto-loan APR/term the client calculator uses, which must be the same values materialization reads.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import Plans, Vehicle, VehiclePlan
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.vehicle import VehicleForm, _TYPICAL_PRICE, _TYPICAL_REPLACEMENT_YEARS
from ucfp.inputs.vehicle_expenses import vehicle_plan_of


def _apply( **fields ) -> Vehicle:
    """Submit a complete vehicle (the given fields over sensible required defaults) and return the
    materialized `Vehicle` the form writes."""
    data = QueryDict( mutable = True )
    submitted = { 'name': 'Car', 'purchase_date': '2030-01-01', 'purchase_price': '35,000',
                  'recurrence_years': '7' }
    submitted.update( fields )
    data.update( submitted )
    form = VehicleForm( data, plans = Plans(), handle = 'vehicle-1' )
    assert form.is_valid(), form.errors
    _profile, plans = form.apply( Profile(), Plans() )
    return vehicle_plan_of( plans ).vehicles[ 0 ]


class VehiclePaymentMethodTests( unittest.TestCase ):

    def test_defaults_seed_a_cash_purchase_at_the_typicals( self ):
        defaults = VehicleForm._defaults( 'vehicle-3' )
        self.assertEqual( defaults[ 'payment_method' ], PaymentMethod.CASH.name )
        self.assertEqual( defaults[ 'purchase_price' ], _TYPICAL_PRICE )
        self.assertEqual( defaults[ 'recurrence_years' ], _TYPICAL_REPLACEMENT_YEARS )

    def test_a_blank_method_applies_as_cash( self ):
        # The radio is not required; a submit without it falls back to cash rather than erroring.
        self.assertIs( _apply().payment_method, PaymentMethod.CASH )

    def test_a_loan_carries_its_down_payment( self ):
        vehicle = _apply( payment_method = 'LOAN', down_payment = '5,000', monthly_payment = '601' )
        self.assertIs( vehicle.payment_method, PaymentMethod.LOAN )
        self.assertEqual( vehicle.down_payment, Decimal( '5000' ) )
        self.assertEqual( vehicle.monthly_payment, Decimal( '601' ) )

    def test_a_lease_carries_all_three_payment_fields( self ):
        vehicle = _apply( payment_method = 'LEASE', down_payment = '3,000',
                          monthly_payment = '400', lease_end_payment = '500' )
        self.assertIs( vehicle.payment_method, PaymentMethod.LEASE )
        self.assertEqual( vehicle.down_payment, Decimal( '3000' ) )
        self.assertEqual( vehicle.monthly_payment, Decimal( '400' ) )
        self.assertEqual( vehicle.lease_end_payment, Decimal( '500' ) )

    def test_an_existing_vehicles_method_pre_fills_on_edit( self ):
        existing = Vehicle(
            handle = 'vehicle-1', name = 'Car', purchase_date = date( 2030, 1, 1 ),
            purchase_price = Decimal( '35000' ), recurrence_years = 7, payment_method = PaymentMethod.LEASE )
        plans = Plans( vehicle_plan = VehiclePlan( vehicles = [ existing ] ) )
        form  = VehicleForm( plans = plans, handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'payment_method' ], PaymentMethod.LEASE.name )


class VehicleFinanceAssumptionTests( unittest.TestCase ):
    """The APR/term the form feeds the client calculator are the same built-in values materialization
    amortizes at, so the on-screen estimate and the forecast agree."""

    def test_apr_and_term_match_the_builtin_assumptions( self ):
        form = VehicleForm( handle = 'vehicle-1' )
        self.assertEqual( form.auto_loan_apr_percent,
                          float( BUILTIN_ASSUMPTIONS.auto_loan_apr.fraction * 100 ) )
        self.assertEqual( form.auto_loan_term_months, BUILTIN_ASSUMPTIONS.auto_loan_term_months )
        self.assertEqual( form.auto_loan_term_years, BUILTIN_ASSUMPTIONS.auto_loan_term_years )


class VehicleSwitchTokenTests( unittest.TestCase ):
    """The switch's method vocabulary comes from PaymentMethod through the form -- the case strings and
    the finances marker -- so `inputs.js` and the template carry no member-name literals, and a rename
    stays consistent (the radio values are the same names)."""

    @staticmethod
    def _rendered():
        return render_to_string(
            'inputs/interview/sections/vehicle_form.html',
            { 'vehicle_form': VehicleForm( handle = 'vehicle-1' ), 'handle': 'vehicle-1',
              'AppConst': AppConst } )

    def test_case_strings_derive_from_the_payment_method_members( self ):
        form = VehicleForm( handle = 'vehicle-1' )
        self.assertEqual( form.payment_field_methods,
                          f'{PaymentMethod.LOAN.name} {PaymentMethod.LEASE.name}' )
        self.assertEqual( form.lease_only_method, PaymentMethod.LEASE.name )
        self.assertEqual( form.financing_method, PaymentMethod.LOAN.name )

    def test_the_radio_values_are_the_member_names( self ):
        # The radios and the case strings both use the member names, so a field shows for exactly the
        # methods that name it -- the invariant that keeps the switch working across a rename.
        values = [ choice[ 0 ] for choice in VehicleForm( handle = 'v' ).fields[ 'payment_method' ].choices ]
        self.assertEqual( set( values ), { method.name for method in PaymentMethod } )

    def test_only_the_loan_option_carries_the_finances_marker( self ):
        html = self._rendered()
        flag = f'data-{AppConst.VEHICLE_FINANCES_DATA_ATTR}'
        self.assertEqual( html.count( flag ), 1 )                       # exactly one option flagged
        after_flag = html[ html.find( flag ) : ]
        self.assertIn( f'value="{PaymentMethod.LOAN.name}"', after_flag[ :200 ] )   # ...the loan radio

    def test_the_rendered_switch_cases_come_from_the_form_properties( self ):
        # The case values in the HTML are the form's derived strings, not hardcoded member names -- the
        # one server-side contract a JS screenshot cannot cover.
        form = VehicleForm( handle = 'vehicle-1' )
        html = self._rendered()
        attr = f'data-{AppConst.SWITCH_CASE_DATA_ATTR}'
        self.assertIn( f'{attr}="{form.payment_field_methods}"', html )
        self.assertIn( f'{attr}="{form.lease_only_method}"', html )

    def test_the_down_field_is_labelled_conditionally_by_method( self ):
        # One down field, two switch-cased labels -- "Down payment" for a loan, "Due at signing" for a
        # lease -- their case values from the form, so the method names stay out of the template.
        html = self._rendered()
        attr = f'data-{AppConst.SWITCH_CASE_DATA_ATTR}'
        self.assertIn( f'{attr}="{PaymentMethod.LOAN.name}">Down payment', html )
        self.assertIn( f'{attr}="{PaymentMethod.LEASE.name}">Due at signing', html )


class VehicleReplacesLinkTests( unittest.TestCase ):
    """The optional link to a current vehicle possession round-trips through the form, and the dropdown
    lists the current vehicles -- shown only when the household has one."""

    @staticmethod
    def _profile():
        return Profile( assets = [ AssetProfile(
            handle = 'possession-1', name = 'Old Car', asset_class = AssetClass.DEPRECIATING,
            opening_value = Decimal( '20000' ) ) ] )

    def test_a_submitted_link_is_carried_onto_the_vehicle( self ):
        data = QueryDict( mutable = True )
        data.update( { 'name': 'Car', 'purchase_date': '2030-01-01', 'purchase_price': '35,000',
                       'recurrence_years': '7', 'replaces_vehicle': 'possession-1' } )
        form = VehicleForm( data, profile = self._profile(), plans = Plans(), handle = 'vehicle-1' )
        assert form.is_valid(), form.errors
        _profile, plans = form.apply( self._profile(), Plans() )
        self.assertEqual( vehicle_plan_of( plans ).vehicles[ 0 ].replaces_vehicle, 'possession-1' )

    def test_no_link_leaves_it_unset( self ):
        data = QueryDict( mutable = True )
        data.update( { 'name': 'Car', 'purchase_date': '2030-01-01', 'purchase_price': '35,000',
                       'recurrence_years': '7' } )                          # replaces_vehicle blank
        form = VehicleForm( data, profile = self._profile(), plans = Plans(), handle = 'vehicle-1' )
        assert form.is_valid(), form.errors
        _profile, plans = form.apply( self._profile(), Plans() )
        self.assertIsNone( vehicle_plan_of( plans ).vehicles[ 0 ].replaces_vehicle )

    def test_the_link_pre_fills_on_edit( self ):
        car = Vehicle( handle = 'vehicle-1', name = 'Car', purchase_date = date( 2030, 1, 1 ),
                       purchase_price = Decimal( '35000' ), recurrence_years = 7,
                       replaces_vehicle = 'possession-1' )
        plans = Plans( vehicle_plan = VehiclePlan( vehicles = [ car ] ) )
        form  = VehicleForm( profile = self._profile(), plans = plans, handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'replaces_vehicle' ], 'possession-1' )

    def test_the_dropdown_lists_current_vehicles_only_when_present( self ):
        self.assertEqual( VehicleForm( handle = 'vehicle-1' ).replaceable_vehicles, [] )
        self.assertEqual(
            VehicleForm( profile = self._profile(), handle = 'vehicle-1' ).replaceable_vehicles,
            [ ( 'possession-1', 'Old Car' ) ] )


if __name__ == '__main__':
    unittest.main()
