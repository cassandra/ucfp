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
from ucfp.forecast.parameters import ScheduledLoanPayoff, ScheduledPurchase, ScheduledRealization
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import (
    HealthCoverageAssumption, Plans, PropertyExpense, Vehicle, VehiclePlan, VehicleRunningCost )
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext, Realization
from ucfp.planning.materialization import (
    _health_coverage, _property_expenses, _vehicle_expenses, _vehicle_holdings, _vehicle_loans,
    _vehicle_purchase_events, _vehicle_running_costs )

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


_HORIZON = date( 2060, 12, 31 )


class CashVehicleTests( unittest.TestCase ):
    """A CASH vehicle is an owned, depreciating holding, not an expense: it emits no purchase expense
    item, a zero-opening DEPRECIATING holding, and a realize-then-buy event pair at each replacement
    (the sale trades the outgoing car in; the first buy has nothing to trade)."""

    @staticmethod
    def _plans( *vehicles ):
        return Plans( vehicle_plan = VehiclePlan( vehicles = list( vehicles ) ) )

    def test_cash_vehicle_emits_no_purchase_expense( self ):
        cash = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        self.assertEqual( _vehicle_expenses( self._plans( cash ) ), [] )

    def test_cash_vehicle_declares_a_zero_opening_depreciating_holding( self ):
        cash = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 5, name = 'Sedan' )
        holdings = _vehicle_holdings( self._plans( cash ) )
        self.assertEqual( len( holdings ), 1 )
        self.assertEqual( holdings[ 0 ].asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( holdings[ 0 ].opening_value, Decimal( '0' ) )
        self.assertEqual( holdings[ 0 ].handle, 'vehicle:vehicle-1' )

    def test_cash_replacement_cycles_realize_then_buy_into_the_holding( self ):
        cash = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2036, 6, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        events = _vehicle_purchase_events( self._plans( cash ), _HORIZON )
        # Buys at 2026, 2031, 2036 (every 5y through the end date), each a realize (trade-in) then a buy.
        self.assertEqual(
            [ ( type( e ).__name__, e.event_date ) for e in events ],
            [ ( 'ScheduledRealization', date( 2026, 1, 1 ) ), ( 'ScheduledPurchase', date( 2026, 1, 1 ) ),
              ( 'ScheduledRealization', date( 2031, 1, 1 ) ), ( 'ScheduledPurchase', date( 2031, 1, 1 ) ),
              ( 'ScheduledRealization', date( 2036, 1, 1 ) ), ( 'ScheduledPurchase', date( 2036, 1, 1 ) ) ] )
        buys = [ e for e in events if isinstance( e, ScheduledPurchase ) ]
        self.assertTrue( all( e.asset == 'vehicle:vehicle-1' for e in buys ) )
        self.assertTrue( all( e.amount == Decimal( '30000' ) for e in buys ) )
        sales = [ e for e in events if isinstance( e, ScheduledRealization ) ]
        self.assertTrue( all( e.amount is None for e in sales ) )   # sell the whole (depreciated) holding

    def test_ongoing_cash_vehicle_buys_through_the_horizon( self ):
        cash = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 10 )
        buys = [ e for e in _vehicle_purchase_events( self._plans( cash ), _HORIZON )
                 if isinstance( e, ScheduledPurchase ) ]
        self.assertEqual( [ e.event_date.year for e in buys ], [ 2026, 2036, 2046, 2056 ] )

    def test_incomplete_cash_vehicle_emits_no_holding_or_events( self ):
        bare = self._plans( _vehicle( 'vehicle-1', date( 2026, 1, 1 ) ) )
        self.assertEqual( _vehicle_holdings( bare ), [] )
        self.assertEqual( _vehicle_purchase_events( bare, _HORIZON ), [] )


class FinancedVehicleTests( unittest.TestCase ):
    """A LOAN vehicle is an owned depreciating holding (like cash) financed by a real recurring loan: no
    purchase expense, an owned holding, one loan originated per replacement cycle, and the outgoing car's
    loan paid off at each trade-in."""

    @staticmethod
    def _plans( *vehicles ):
        return Plans( vehicle_plan = VehiclePlan( vehicles = list( vehicles ) ) )

    def _financed( self, **kwargs ):
        return _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2036, 6, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 5,
                         payment_method = PaymentMethod.LOAN, **kwargs )

    def test_financed_vehicle_emits_no_purchase_expense_but_owns_a_holding( self ):
        plans = self._plans( self._financed( down_payment = Decimal( '5000' ) ) )
        self.assertEqual( _vehicle_expenses( plans ), [] )
        holdings = _vehicle_holdings( plans )
        self.assertEqual( len( holdings ), 1 )
        self.assertEqual( holdings[ 0 ].asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( holdings[ 0 ].handle, 'vehicle:vehicle-1' )

    def test_a_loan_is_originated_each_cycle_for_the_financed_amount( self ):
        loans = _vehicle_loans( self._plans( self._financed( down_payment = Decimal( '5000' ) ) ), _HORIZON )
        # Buys at 2026, 2031, 2036 -> a loan originated at each, financing price - down.
        self.assertEqual( [ loan.origination_date for loan in loans ],
                          [ date( 2026, 1, 1 ), date( 2031, 1, 1 ), date( 2036, 1, 1 ) ] )
        self.assertTrue( all( loan.opening_balance == Decimal( '25000' ) for loan in loans ) )
        self.assertEqual( { loan.handle for loan in loans },
                          { 'vehicle-loan:vehicle-1:0', 'vehicle-loan:vehicle-1:1', 'vehicle-loan:vehicle-1:2' } )

    def test_replacement_pays_off_the_prior_cycles_loan( self ):
        events  = _vehicle_purchase_events( self._plans( self._financed( down_payment = Decimal( '5000' ) ) ),
                                            _HORIZON )
        payoffs = [ e for e in events if isinstance( e, ScheduledLoanPayoff ) ]
        # No payoff at the first buy; each later replacement settles the previous cycle's loan.
        self.assertEqual( [ ( e.event_date, e.loan ) for e in payoffs ],
                          [ ( date( 2031, 1, 1 ), 'vehicle-loan:vehicle-1:0' ),
                            ( date( 2036, 1, 1 ), 'vehicle-loan:vehicle-1:1' ) ] )
        # The holding still cycles (realize + buy), like a cash car.
        self.assertTrue( any( isinstance( e, ScheduledPurchase ) for e in events ) )
        self.assertTrue( any( isinstance( e, ScheduledRealization ) for e in events ) )

    def test_financed_amount_derives_from_the_monthly_when_no_down_given( self ):
        # No-JS fallback: only a monthly entered -> the principal is what that payment finances (so the
        # down is implied), not the whole price.
        loans = _vehicle_loans( self._plans( self._financed( monthly_payment = Decimal( '500' ) ) ), _HORIZON )
        self.assertGreater( loans[ 0 ].opening_balance, Decimal( '0' ) )
        self.assertLess( loans[ 0 ].opening_balance, Decimal( '30000' ) )   # not the whole price


class LeasedVehicleTests( unittest.TestCase ):
    """A LEASE vehicle is pure expense -- down, monthly, and lease-end payments -- with no owned
    holding and no trade-in."""

    @staticmethod
    def _plans( *vehicles ):
        return Plans( vehicle_plan = VehiclePlan( vehicles = list( vehicles ) ) )

    def test_lease_emits_down_monthly_and_lease_end( self ):
        lease = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2040, 1, 1 ),
                          purchase_price = Decimal( '30000' ), recurrence_years = 3,
                          payment_method = PaymentMethod.LEASE, down_payment = Decimal( '3000' ),
                          monthly_payment = Decimal( '400' ), lease_end_payment = Decimal( '500' ) )
        items = _vehicle_expenses( self._plans( lease ) )
        self.assertEqual( [ item.name for item in items ], [ 'Car lease', 'Car payments', 'Car lease' ] )
        monthly = next( item for item in items if item.name == 'Car payments' )
        self.assertEqual( monthly.amounts.segments[ 0 ].amount, Decimal( '400' ) )
        # the lease-end lump starts one lease term in (the end of the first term), not at purchase
        lease_end = items[ 2 ]
        self.assertEqual( lease_end.window.start, date( 2029, 1, 1 ) )
        self.assertEqual( lease_end.amounts.segments[ 0 ].amount, Decimal( '500' ) )

    def test_lease_has_no_owned_holding( self ):
        lease = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                          purchase_price = Decimal( '30000' ), recurrence_years = 3,
                          payment_method = PaymentMethod.LEASE, down_payment = Decimal( '3000' ),
                          monthly_payment = Decimal( '400' ) )
        self.assertEqual( _vehicle_holdings( self._plans( lease ) ), [] )


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
