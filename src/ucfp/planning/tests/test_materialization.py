"""Materialization of property operating expenses: the tax-class derivation.

A `PropertyExpense` stores its *personal* tax class (`SALT` for property tax, `LIVING` otherwise);
materialization derives the class the engine sees from the property each shared amount lands on -- a
rental's operating cost nets as a `RENTAL_EXPENSE`, while a personal dwelling's (and a rented-home
flow, which has no owned asset) keeps its stored personal class. This mirrors the mortgage-interest
derivation tested end-to-end in `ucfp.forecast.tests.test_rental`.
"""
import unittest
from decimal import Decimal

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.inputs.plans.schemas import Plans, PropertyExpense, VehiclePlan, VehicleRunningCost
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext, Realization
from ucfp.planning.materialization import _property_expenses, _vehicle_running_costs

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
        name = 'Upkeep', category = ExpenseCategory.MAINTENANCE_REPAIR, expense_tax_class = tax_class,
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


class VehicleRunningCostTests( unittest.TestCase ):
    """A vehicle running cost is a per-car amount scaled by the plan's car count, then materialized by
    its realization -- SMOOTH annualized into a stream, DISCRETE placed as an item at its cadence."""

    @staticmethod
    def _plans( num_cars, *costs ):
        return Plans( vehicle_plan = VehiclePlan( num_cars = num_cars, running_costs = list( costs ) ) )

    @staticmethod
    def _cost( realization, interval, amount = Decimal( '20' ) ):
        return VehicleRunningCost(
            name = 'Gasoline', expense_tax_class = ExpenseTaxClass.LIVING,
            interval = interval, amount = amount, realization = realization )

    def test_smooth_cost_scales_by_num_cars_then_annualizes( self ):
        # $20/car/week x 2 cars = $40/week, annualized x 52 = $2,080/yr stream (no item).
        streams, items = _vehicle_running_costs(
            self._plans( 2, self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ) )
        self.assertEqual( items, [] )
        self.assertEqual( streams[ 0 ].amounts.segments[ 0 ].amount, Decimal( '2080' ) )

    def test_discrete_cost_scales_by_num_cars_at_its_cadence( self ):
        # $750/car semiannually x 2 cars = a $1,500 item every 6 months (no stream).
        semiannual = Duration( 6, TimeUnit.MONTH )
        streams, items = _vehicle_running_costs(
            self._plans( 2, self._cost( Realization.DISCRETE, semiannual, Decimal( '750' ) ) ) )
        self.assertEqual( streams, [] )
        self.assertEqual( items[ 0 ].cadence.interval, semiannual )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '1500' ) )

    def test_no_cars_or_blank_amount_yields_nothing( self ):
        weekly = Duration( 1, TimeUnit.WEEK )
        self.assertEqual(                                  # a blank per-car amount is not charged
            _vehicle_running_costs( self._plans( 2, self._cost( Realization.SMOOTH, weekly, None ) ) ),
            ( [], [] ) )
        self.assertEqual(                                  # no cars -> nothing to scale
            _vehicle_running_costs( self._plans( None, self._cost( Realization.SMOOTH, weekly ) ) ),
            ( [], [] ) )
