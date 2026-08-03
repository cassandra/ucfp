"""Materialization of property operating expenses: the tax-class derivation.

A `PropertyExpense` stores its *personal* tax class (`SALT` for property tax, `LIVING` otherwise);
materialization derives the class the engine sees from the property each shared amount lands on -- a
rental's operating cost nets as a `RENTAL_EXPENSE`, while a personal dwelling's (and a rented-home
flow, which has no owned asset) keeps its stored personal class. This mirrors the mortgage-interest
derivation tested end-to-end in `ucfp.forecast.tests.test_rental`.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.inputs.plans.schemas import (
    HealthCoverageAssumption, Plans, PropertyExpense, Vehicle, VehiclePlan, VehicleRunningCost )
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext, Realization
from ucfp.planning.materialization import (
    _health_coverage, _property_expenses, _vehicle_expenses, _vehicle_running_costs )

_OWNED    = ( PropertyContext.RESIDENCE, PropertyContext.SECOND_HOME, PropertyContext.RENTAL )
_OCCUPIED = _OWNED + ( PropertyContext.RENTED_HOME, )


def _property( handle : str, asset_class : AssetClass ) -> AssetProfile:
    return AssetProfile(
        handle = handle, name = handle.title(), asset_class = asset_class,
        opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) )


def _expense( applies_to, tax_class,
              realization = Realization.SMOOTH, interval = Duration( 1, TimeUnit.YEAR ) ) -> PropertyExpense:
    # One shared property expense at a flat default, applied to the contexts in `applies_to`.
    return PropertyExpense(
        name = 'Upkeep', handle = 'upkeep', category = ExpenseCategory.MAINTENANCE_REPAIR,
        expense_tax_class = tax_class,
        applies_to = applies_to, realization = realization, interval = interval,
        default_amount = Decimal( '6000' ) )


class PropertyExpenseTaxClassTests( unittest.TestCase ):

    def test_rental_property_expense_derives_rental_expense( self ):
        # One SALT property-tax expense applied to every owned dwelling: only the rental's derives to a
        # (rent-netting) rental expense. A second home is personal-use like the residence, so its tax
        # stays SALT -- the non-obvious fall-through (it is not netted like a rental).
        profile = Profile( assets = [
            _property( 'residence', AssetClass.REAL_ESTATE_RESIDENCE ),
            _property( 'second-home', AssetClass.REAL_ESTATE_SECOND_HOME ),
            _property( 'rental', AssetClass.REAL_ESTATE_RENTAL ) ] )
        plans = Plans( property_expenses = [ _expense( _OWNED, ExpenseTaxClass.SALT ) ] )
        streams, _items = _property_expenses(
            profile, plans, { a.handle : a for a in profile.assets }, dict() )
        self.assertEqual(
            [ stream.expense_tax_class for stream in streams ],
            [ ExpenseTaxClass.SALT, ExpenseTaxClass.SALT, ExpenseTaxClass.RENTAL_EXPENSE ] )

    def test_rented_home_flow_keeps_its_personal_class( self ):
        # A tenant's rented home (a handle with no owned asset, present when the tenure is RENT) takes
        # occupied expenses (utilities, rent) and falls through to the stored personal class -- never a
        # rental expense.
        profile = Profile( home_tenure = HousingTenure.RENT )
        plans = Plans( property_expenses = [ _expense( _OCCUPIED, ExpenseTaxClass.LIVING ) ] )
        streams, _items = _property_expenses( profile, plans, dict(), dict() )
        self.assertEqual( [ s.expense_tax_class for s in streams ], [ ExpenseTaxClass.LIVING ] )


class RealizationTests( unittest.TestCase ):

    def _residence_plans( self, realization, interval ):
        profile = Profile( assets = [ _property( 'residence', AssetClass.REAL_ESTATE_RESIDENCE ) ] )
        plans   = Plans( property_expenses = [ _expense(
            ( PropertyContext.RESIDENCE, ), ExpenseTaxClass.LIVING,
            realization = realization, interval = interval ) ] )
        return _property_expenses( profile, plans, { 'residence': _property(
            'residence', AssetClass.REAL_ESTATE_RESIDENCE ) }, dict() )

    def test_discrete_expense_is_an_item_at_its_cadence( self ):
        # A DISCRETE expense is placed as an item at its interval, not smoothed into a stream.
        yearly = Duration( 1, TimeUnit.YEAR )
        streams, items = self._residence_plans( Realization.DISCRETE, yearly )
        self.assertEqual( streams, [] )
        self.assertEqual( [ item.cadence.interval for item in items ], [ yearly ] )

    def test_smooth_annualizes_a_sub_annual_amount( self ):
        # A monthly $6,000 SMOOTH expense enters as a $72,000/yr stream level (6000 x 12), not an item.
        streams, items = self._residence_plans( Realization.SMOOTH, Duration( 1, TimeUnit.MONTH ) )
        self.assertEqual( items, [] )
        self.assertEqual( streams[ 0 ].amounts.segments[ 0 ].amount, Decimal( '72000' ) )


def _vehicle( handle, purchase_date, end_date = None, **kwargs ) -> Vehicle:
    return Vehicle( handle = handle, purchase_date = purchase_date, end_date = end_date, **kwargs )


class VehiclePurchaseTests( unittest.TestCase ):
    """Each vehicle's purchase materializes within its own ownership window -- so several cars buy in
    their own years rather than all at once -- sharing the Car purchase / Car payments accounts."""

    @staticmethod
    def _plans( *vehicles ):
        return Plans( vehicle_plan = VehiclePlan( vehicles = list( vehicles ) ) )

    def test_each_vehicle_purchases_in_its_own_window( self ):
        v1 = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                       purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        v2 = _vehicle( 'vehicle-2', date( 2028, 1, 1 ), end_date = date( 2040, 1, 1 ),
                       purchase_price = Decimal( '40000' ), recurrence_years = 8 )
        items = _vehicle_expenses( self._plans( v1, v2 ) )
        self.assertEqual( [ item.name for item in items ], [ 'Car purchase', 'Car purchase' ] )
        # the ongoing car is unbounded on the end; the retired one carries its full [purchase, end] window
        self.assertEqual( items[ 0 ].window, DateWindow( start = date( 2026, 1, 1 ) ) )
        self.assertEqual( items[ 1 ].window,
                          DateWindow( start = date( 2028, 1, 1 ), end = date( 2040, 1, 1 ) ) )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '30000' ) )  # cash: full price

    def test_incomplete_vehicle_emits_nothing( self ):
        self.assertEqual( _vehicle_expenses( self._plans( _vehicle( 'vehicle-1', date( 2026, 1, 1 ) ) ) ), [] )

    def test_financed_vehicle_splits_into_down_and_payments( self ):
        vehicle = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2038, 1, 1 ),
                            purchase_price = Decimal( '30000' ), recurrence_years = 5,
                            down_payment = Decimal( '5000' ) )
        items = _vehicle_expenses( self._plans( vehicle ) )
        self.assertEqual( { item.name for item in items }, { 'Car purchase', 'Car payments' } )
        purchase = next( item for item in items if item.name == 'Car purchase' )
        payments = next( item for item in items if item.name == 'Car payments' )
        self.assertEqual( purchase.amounts.segments[ 0 ].amount, Decimal( '5000' ) )  # the down payment is the lump
        window = DateWindow( start = date( 2026, 1, 1 ), end = date( 2038, 1, 1 ) )
        self.assertEqual( purchase.window, window )     # both items carry the vehicle's ownership window
        self.assertEqual( payments.window, window )


class VehicleRunningCostTests( unittest.TestCase ):
    """A running cost is a per-car amount emitted once per owned vehicle, gated to that vehicle's window
    -- so the total ramps with the fleet. SMOOTH annualizes into a stream, DISCRETE places an item."""

    @staticmethod
    def _plans( vehicles, *costs ):
        return Plans( vehicle_plan = VehiclePlan(
            vehicles = list( vehicles ), running_costs = list( costs ) ) )

    @staticmethod
    def _cost( realization, interval, amount = Decimal( '20' ) ):
        return VehicleRunningCost(
            name = 'Gasoline', handle = 'gasoline', expense_tax_class = ExpenseTaxClass.LIVING,
            interval = interval, amount = amount, realization = realization )

    def test_smooth_cost_is_one_annualized_stream_per_vehicle( self ):
        # $20/car/week annualized x 52 = $1,040/yr, one stream per vehicle, each in its own window.
        v1 = _vehicle( 'vehicle-1', date( 2026, 1, 1 ) )
        v2 = _vehicle( 'vehicle-2', date( 2028, 1, 1 ), end_date = date( 2035, 1, 1 ) )
        streams, items = _vehicle_running_costs(
            self._plans( [ v1, v2 ], self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ) )
        self.assertEqual( items, [] )
        self.assertEqual( len( streams ), 2 )
        self.assertEqual( streams[ 0 ].amounts.segments[ 0 ].amount, Decimal( '1040' ) )   # per car, not scaled
        self.assertEqual( streams[ 0 ].window, DateWindow( start = date( 2026, 1, 1 ) ) )
        self.assertEqual( streams[ 1 ].window, DateWindow( start = date( 2028, 1, 1 ), end = date( 2035, 1, 1 ) ) )

    def test_discrete_cost_is_an_item_per_vehicle_at_its_cadence( self ):
        semiannual = Duration( 6, TimeUnit.MONTH )
        vehicle = _vehicle( 'vehicle-1', date( 2026, 1, 1 ) )
        streams, items = _vehicle_running_costs(
            self._plans( [ vehicle ], self._cost( Realization.DISCRETE, semiannual, Decimal( '750' ) ) ) )
        self.assertEqual( streams, [] )
        self.assertEqual( items[ 0 ].cadence.interval, semiannual )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '750' ) )   # per car

    def test_blank_amount_or_no_vehicle_yields_nothing( self ):
        weekly  = Duration( 1, TimeUnit.WEEK )
        vehicle = _vehicle( 'vehicle-1', date( 2026, 1, 1 ) )
        self.assertEqual(                                  # a blank per-car amount is not charged
            _vehicle_running_costs( self._plans( [ vehicle ], self._cost( Realization.SMOOTH, weekly, None ) ) ),
            ( [], [] ) )
        self.assertEqual(                                  # no vehicles -> nothing to apply
            _vehicle_running_costs( self._plans( [], self._cost( Realization.SMOOTH, weekly ) ) ),
            ( [], [] ) )


class HealthCoverageDefaultTests( unittest.TestCase ):
    """`_health_coverage` resolves the input's optional actual premium: unset means "assume the
    benchmark plan" (default to the reference premium), so the ACA credit's actual-premium cap does
    not bind until the user names a cheaper plan; an explicit actual premium passes through."""

    def test_unset_actual_premium_defaults_to_the_reference_premium( self ):
        plans = Plans( health_coverage = HealthCoverageAssumption(
            household_size = 1, reference_premium = Decimal( '8000' ) ) )
        self.assertEqual( _health_coverage( plans ).actual_premium, Decimal( '8000' ) )

    def test_explicit_actual_premium_passes_through( self ):
        plans = Plans( health_coverage = HealthCoverageAssumption(
            household_size = 1, reference_premium = Decimal( '8000' ), actual_premium = Decimal( '5000' ) ) )
        self.assertEqual( _health_coverage( plans ).actual_premium, Decimal( '5000' ) )
