"""VehicleForm: the payment method round-trips through the form and drives the derived Vehicle.

The method radio is not required (a blank submit falls back to cash), the per-method payment fields are
carried onto the `Vehicle`, and an existing vehicle's method pre-fills on edit. The form also surfaces the
assumed auto-loan APR/term the client calculator uses, which must be the same values materialization reads.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.http import QueryDict

from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import Plans, Vehicle, VehiclePlan
from ucfp.inputs.profile.schemas import Profile
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


if __name__ == '__main__':
    unittest.main()
