"""Materialization of property operating expenses: the tax-class derivation.

A `PropertyExpense` stores its *personal* tax class (`SALT` for property tax, `LIVING` otherwise);
materialization derives the class the engine sees from the property each shared amount lands on -- a
rental's operating cost nets as a `RENTAL_EXPENSE`, while a personal dwelling's (and a rented-home
flow, which has no owned asset) keeps its stored personal class. This mirrors the mortgage-interest
derivation tested end-to-end in `ucfp.forecast.tests.test_rental`.
"""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.recurrence import Duration, Recurrence, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.parameters import RecurringHoldingPurchase
from ucfp.inputs.plans.enums import LeaseDispositionKind, PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    HealthCoverageAssumption, LeasedVehicleDisposition, Plans, PropertyExpense, Vehicle,
    VehicleDisposition, VehiclePlan, VehicleRunningCost )
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext, Realization
from ucfp.planning.materialization import (
    _assets, _health_coverage, _leased_current_expenses, _property_expenses, _vehicle_expenses,
    _vehicle_holding_purchases, _vehicle_holdings, _vehicle_loan_originations, _vehicle_running_costs )

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

    def test_cash_vehicle_declares_one_trade_in_recurring_purchase( self ):
        # The cash car is one recurring, inflation-indexed replacement (trade the whole old car in, rebuy);
        # the engine owns the cadence and inflation, so materialization declares only the intent, not the
        # enumerated per-cycle events.
        cash = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2036, 6, 1 ),
                         purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        purchases = _vehicle_holding_purchases( self._plans( cash ) )
        self.assertEqual( purchases, [ RecurringHoldingPurchase(
            holding = 'vehicle:vehicle-1', price = Decimal( '30000' ),
            interval = Duration( 5, TimeUnit.YEAR ),
            window = DateWindow( start = date( 2026, 1, 1 ), end = date( 2036, 6, 1 ) ),
            trade_in = True ) ] )

    def test_incomplete_cash_vehicle_emits_no_holding_or_purchase( self ):
        bare = self._plans( _vehicle( 'vehicle-1', date( 2026, 1, 1 ) ) )
        self.assertEqual( _vehicle_holdings( bare ), [] )
        self.assertEqual( _vehicle_holding_purchases( bare ), [] )


class FinancedVehicleTests( unittest.TestCase ):
    """A LOAN vehicle is an owned depreciating holding (like cash) plus a recurring loan origination: no
    purchase expense, an owned holding, and one financing declaration the engine expands into a per-cycle
    loan (with the rollover payoff) -- the per-cycle enumeration and inflation are the engine's, tested in
    the forecast layer."""

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

    def test_a_loan_origination_is_declared_for_the_financed_amount( self ):
        originations = _vehicle_loan_originations(
            self._plans( self._financed( down_payment = Decimal( '5000' ) ) ) )
        self.assertEqual( len( originations ), 1 )      # one recurring declaration; the engine expands cycles
        origination = originations[ 0 ]
        self.assertEqual( origination.principal, Decimal( '25000' ) )        # price - down, today's dollars
        self.assertEqual( origination.handle, 'vehicle-loan:vehicle-1' )     # engine appends the cycle
        self.assertEqual( origination.interest_handle, 'vehicle-loan-interest:vehicle-1' )
        self.assertEqual( origination.interval, Duration( 5, TimeUnit.YEAR ) )
        self.assertEqual( origination.window,
                          DateWindow( start = date( 2026, 1, 1 ), end = date( 2036, 6, 1 ) ) )

    def test_financed_amount_derives_from_the_monthly_when_no_down_given( self ):
        # No-JS fallback: only a monthly entered -> the principal is what that payment finances (so the
        # down is implied), not the whole price.
        originations = _vehicle_loan_originations(
            self._plans( self._financed( monthly_payment = Decimal( '500' ) ) ) )
        self.assertGreater( originations[ 0 ].principal, Decimal( '0' ) )
        self.assertLess( originations[ 0 ].principal, Decimal( '30000' ) )   # not the whole price

    def test_a_fully_down_loan_finances_nothing( self ):
        # down >= price: nothing to finance, so no loan origination is declared -- it behaves like a cash
        # purchase (one recurring holding replacement), still owning the holding.
        plans = self._plans( self._financed( down_payment = Decimal( '30000' ) ) )
        self.assertEqual( _vehicle_loan_originations( plans ), [] )
        self.assertEqual( len( _vehicle_holding_purchases( plans ) ), 1 )
        self.assertEqual( len( _vehicle_holdings( plans ) ), 1 )


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
        # the lease-end lump starts one lease term in (the end of the first term), not at purchase, and
        # recurs each term (not a one-shot)
        lease_end = items[ 2 ]
        self.assertEqual( lease_end.window.start, date( 2029, 1, 1 ) )
        self.assertEqual( lease_end.cadence, Recurrence( Duration( 3, TimeUnit.YEAR ) ) )
        self.assertEqual( lease_end.amounts.segments[ 0 ].amount, Decimal( '500' ) )

    def test_lease_has_no_owned_holding( self ):
        lease = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                          purchase_price = Decimal( '30000' ), recurrence_years = 3,
                          payment_method = PaymentMethod.LEASE, down_payment = Decimal( '3000' ),
                          monthly_payment = Decimal( '400' ) )
        self.assertEqual( _vehicle_holdings( self._plans( lease ) ), [] )

    def test_lease_materializes_with_no_purchase_price( self ):
        # A lease is priced by its payments, so the form never collects a purchase price -- its monthly
        # must still materialize. (Regression: readiness once demanded a price no real lease carries, so
        # every lease silently emitted nothing.)
        lease = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), recurrence_years = 3,
                          payment_method = PaymentMethod.LEASE, monthly_payment = Decimal( '400' ) )
        self.assertIsNone( lease.purchase_price )
        items = _vehicle_expenses( self._plans( lease ) )
        self.assertEqual( [ item.name for item in items ], [ 'Car payments' ] )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '400' ) )

    def test_the_monthly_runs_continuously_across_back_to_back_terms( self ):
        # The monthly is one continuous stream to end_date (leases signed back-to-back), not restarted each
        # term; only the lease-end lump recurs per term. A recurrence longer than the real term would over-
        # charge the monthly across the gap -- the UI has one 'replace every', taken as the lease term.
        lease = _vehicle( 'vehicle-1', date( 2026, 1, 1 ), end_date = date( 2038, 1, 1 ),
                          recurrence_years = 3, payment_method = PaymentMethod.LEASE,
                          monthly_payment = Decimal( '400' ), lease_end_payment = Decimal( '500' ) )
        monthly = next( i for i in _vehicle_expenses( self._plans( lease ) ) if i.name == 'Car payments' )
        self.assertEqual( ( monthly.window.start, monthly.window.end ),
                          ( date( 2026, 1, 1 ), date( 2038, 1, 1 ) ) )       # one window across all terms
        self.assertEqual( monthly.cadence, Recurrence( Duration( 1, TimeUnit.MONTH ) ) )


class MixedFleetTests( unittest.TestCase ):
    """A plan mixing cash, loan, and lease vehicles keeps each car's accounts distinct (handle-scoped) and
    applies the right model to each: cash and loan own holdings, only loan originates loans, only lease
    emits expense items."""

    def test_each_method_contributes_only_its_own_artifacts( self ):
        cash  = _vehicle( 'vehicle-1', date( 2027, 1, 1 ), purchase_price = Decimal( '30000' ),
                          recurrence_years = 7, payment_method = PaymentMethod.CASH )
        loan  = _vehicle( 'vehicle-2', date( 2027, 1, 1 ), purchase_price = Decimal( '40000' ),
                          recurrence_years = 7, payment_method = PaymentMethod.LOAN,
                          down_payment = Decimal( '8000' ) )
        lease = _vehicle( 'vehicle-3', date( 2027, 1, 1 ), purchase_price = Decimal( '25000' ),
                          recurrence_years = 3, payment_method = PaymentMethod.LEASE,
                          monthly_payment = Decimal( '350' ) )
        plans = Plans( vehicle_plan = VehiclePlan( vehicles = [ cash, loan, lease ] ) )
        # Cash and loan own holdings (distinct handles); the lease does not.
        self.assertEqual( { holding.handle for holding in _vehicle_holdings( plans ) },
                          { 'vehicle:vehicle-1', 'vehicle:vehicle-2' } )
        # Only the loan vehicle declares a financing origination, scoped to its handle.
        originations = _vehicle_loan_originations( plans )
        self.assertEqual( [ origination.handle for origination in originations ],
                          [ 'vehicle-loan:vehicle-2' ] )
        # Only the lease emits purchase-cost expense items.
        self.assertTrue( _vehicle_expenses( plans ) )

    def test_a_net_new_and_current_vehicle_sharing_a_handle_do_not_collide( self ):
        # The net-new (plan) and current (profile) `vehicle-N` mint spaces overlap as strings, but reach
        # the engine under disjoint prefixes -- a current owned vehicle keeps its bare handle, a net-new
        # becomes `vehicle:<handle>` -- so a shared `vehicle-1` yields two distinct holdings, never one
        # account twice.
        profile = Profile( assets = [ AssetProfile(
            handle = 'vehicle-1', name = 'Current', asset_class = AssetClass.DEPRECIATING,
            opening_value = Decimal( '20000' ) ) ] )
        net_new = _vehicle( 'vehicle-1', date( 2027, 1, 1 ),
                            purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        plans   = Plans( vehicle_plan = VehiclePlan( vehicles = [ net_new ] ) )
        current = { asset.handle for asset in _assets( profile ) }
        planned = { holding.handle for holding in _vehicle_holdings( plans ) }
        self.assertEqual( planned, { 'vehicle:vehicle-1' } )
        self.assertIn( 'vehicle-1', current )
        self.assertEqual( current & planned, set() )              # disjoint despite the shared vehicle-1 stem


class DispositionMaterializationTests( unittest.TestCase ):
    """A Replace disposition's successor materializes exactly as a net-new vehicle does -- an owned
    holding and a recurring purchase -- under a handle derived from the current vehicle and a purchase
    date driven by the disposition. Retain and Sell add no plan vehicle (their effect is the current
    holding's sale, tested at the events layer)."""

    @staticmethod
    def _replacement( price = Decimal( '40000' ), years = 7, method = PaymentMethod.CASH, **kwargs ):
        # The stored replacement spec: identity and first-purchase date are supplied at materialization
        # from the disposition, so they are left off here (as the form stores them).
        return Vehicle( handle = '', purchase_price = price, recurrence_years = years,
                        payment_method = method, **kwargs )

    def _plans( self, kind, when = date( 2030, 1, 1 ), replacement = None ):
        disposition = VehicleDisposition( vehicle_handle = 'vehicle-1', kind = kind, sale_date = when,
                                          replacement = replacement )
        return Plans( vehicle_plan = VehiclePlan( dispositions = [ disposition ] ) )

    def test_replace_successor_becomes_an_owned_recurring_purchase( self ):
        plans     = self._plans( VehicleDispositionKind.REPLACE, replacement = self._replacement() )
        holdings  = _vehicle_holdings( plans )
        purchases = _vehicle_holding_purchases( plans )
        self.assertEqual( [ h.handle for h in holdings ], [ 'vehicle:vehicle-1-replacement' ] )
        self.assertEqual( len( purchases ), 1 )
        self.assertEqual( purchases[ 0 ].holding, 'vehicle:vehicle-1-replacement' )
        self.assertEqual( purchases[ 0 ].price, Decimal( '40000' ) )
        # The successor's first purchase is the handover date the disposition names.
        self.assertEqual( purchases[ 0 ].window.start, date( 2030, 1, 1 ) )

    def test_a_financed_replacement_originates_a_loan_under_the_derived_handle( self ):
        plans = self._plans(
            VehicleDispositionKind.REPLACE,
            replacement = self._replacement( method = PaymentMethod.LOAN, down_payment = Decimal( '8000' ) ) )
        originations = _vehicle_loan_originations( plans )
        self.assertEqual( [ o.handle for o in originations ], [ 'vehicle-loan:vehicle-1-replacement' ] )

    def test_retain_and_sell_add_no_plan_vehicle( self ):
        for kind in ( VehicleDispositionKind.KEEP, VehicleDispositionKind.SELL ):
            plans = self._plans( kind )
            self.assertEqual( _vehicle_holdings( plans ), [], kind )
            self.assertEqual( _vehicle_holding_purchases( plans ), [], kind )

    def test_a_replacement_joins_net_new_vehicles( self ):
        # A net-new vehicle and a Replace successor both materialize, under distinct handles.
        net_new = _vehicle( 'vehicle-2', date( 2028, 1, 1 ), purchase_price = Decimal( '20000' ),
                            recurrence_years = 5 )
        plans   = self._plans( VehicleDispositionKind.REPLACE, replacement = self._replacement() )
        plans   = replace( plans, vehicle_plan = replace( plans.vehicle_plan, vehicles = [ net_new ] ) )
        self.assertEqual( { h.handle for h in _vehicle_holdings( plans ) },
                          { 'vehicle:vehicle-2', 'vehicle:vehicle-1-replacement' } )


class LeasedDispositionMaterializationTests( unittest.TestCase ):
    """A current lease is pure expense -- a monthly item to the day before term end -- and its successor,
    fixed by the kind, begins at lease end: a renewed lease as more expense, a cash buy as an owned
    holding, a loan buy as a financed one. Return adds no successor."""

    _START = date( 2026, 1, 1 )

    def _plans( self, kind, monthly = Decimal( '400' ), lease_end = date( 2029, 1, 1 ), successor = None ):
        disposition = LeasedVehicleDisposition(
            vehicle_handle = 'lease-1', monthly = monthly, lease_end = lease_end, kind = kind,
            successor = successor )
        return Plans( vehicle_plan = VehiclePlan( leased_dispositions = [ disposition ] ) )

    @staticmethod
    def _successor( method, **kwargs ) -> Vehicle:
        # A lease carries no purchase price (it is priced by its payments) -- the form never collects one,
        # so the realistic successor omits it; a cash or financed buy does have one.
        priced = dict() if method is PaymentMethod.LEASE else { 'purchase_price' : Decimal( '30000' ) }
        return Vehicle( handle = '', name = 'Next', recurrence_years = 3,
                        payment_method = method, **priced, **kwargs )

    def test_the_current_lease_charges_the_monthly_to_the_day_before_term_end( self ):
        items = _leased_current_expenses( self._plans( LeaseDispositionKind.RETURN ), self._START )
        self.assertEqual( len( items ), 1 )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '400' ) )
        self.assertEqual( ( items[ 0 ].window.start, items[ 0 ].window.end ),
                          ( self._START, date( 2028, 12, 31 ) ) )      # day before the lease ends

    def test_return_adds_no_successor( self ):
        plans = self._plans( LeaseDispositionKind.RETURN )
        self.assertEqual( _vehicle_holding_purchases( plans ), [] )
        self.assertEqual( _vehicle_expenses( plans ), [] )

    def test_renew_adds_a_recurring_lease_successor( self ):
        plans = self._plans(
            LeaseDispositionKind.RENEW,
            successor = self._successor( PaymentMethod.LEASE, monthly_payment = Decimal( '450' ) ) )
        self.assertEqual( _vehicle_holding_purchases( plans ), [] )     # a lease has no holding
        self.assertTrue( _vehicle_expenses( plans ) )                  # it materializes as lease expense

    def test_buy_cash_adds_an_owned_recurring_purchase_at_lease_end( self ):
        plans = self._plans( LeaseDispositionKind.BUY_CASH,
                             successor = self._successor( PaymentMethod.CASH ) )
        purchases = _vehicle_holding_purchases( plans )
        self.assertEqual( [ p.holding for p in purchases ], [ 'vehicle:lease-1-successor' ] )
        self.assertEqual( purchases[ 0 ].window.start, date( 2029, 1, 1 ) )   # begins at lease end

    def test_buy_loan_finances_the_successor( self ):
        plans = self._plans(
            LeaseDispositionKind.BUY_LOAN,
            successor = self._successor( PaymentMethod.LOAN, down_payment = Decimal( '5000' ) ) )
        self.assertEqual( [ o.handle for o in _vehicle_loan_originations( plans ) ],
                          [ 'vehicle-loan:lease-1-successor' ] )

    def test_a_lease_with_no_monthly_charges_nothing( self ):
        plans = self._plans( LeaseDispositionKind.RETURN, monthly = None )
        self.assertEqual( _leased_current_expenses( plans, self._START ), [] )

    def test_the_current_lease_charges_despite_an_unfinished_successor( self ):
        # Regression: the current lease's monthly is independent of the end-of-term plan. A Renew whose
        # renewed-lease terms are not yet entered is incomplete, but the household still pays the lease it
        # holds now -- only the unready successor waits.
        plans = self._plans( LeaseDispositionKind.RENEW,
                             successor = self._successor( PaymentMethod.LEASE ) )   # no monthly -> incomplete
        self.assertFalse( plans.vehicle_plan.leased_dispositions[ 0 ].is_complete )
        charged = _leased_current_expenses( plans, self._START )
        self.assertEqual( [ item.amounts.segments[ 0 ].amount for item in charged ], [ Decimal( '400' ) ] )
        self.assertEqual( _vehicle_expenses( plans ), [] )                          # the successor waits

    def test_an_elapsed_lease_charges_nothing( self ):
        # A lease whose end is already past (a stale plan, or the start advanced beyond it) is no longer
        # operative -- it emits no monthly (the running-cost window gates on the same operative check).
        plans = self._plans( LeaseDispositionKind.RETURN, lease_end = date( 2025, 1, 1 ) )   # before _START
        self.assertEqual( _leased_current_expenses( plans, self._START ), [] )


class VehicleRunningCostTests( unittest.TestCase ):
    """A running cost is a per-car amount emitted once per *operated* vehicle window -- the current
    vehicle possessions (from the start) and the planned vehicles -- so the total tracks the fleet.
    SMOOTH annualizes into a stream, DISCRETE places an item; a sold possession's window ends at the sale."""

    @staticmethod
    def _plans( vehicles, *costs ):
        return Plans( vehicle_plan = VehiclePlan(
            vehicles = list( vehicles ), running_costs = list( costs ) ) )

    @classmethod
    def _run( cls, plans, profile = None, sale_dates = None, start = date( 2026, 1, 1 ) ):
        return _vehicle_running_costs( profile or Profile(), plans, sale_dates or dict(), start )

    @staticmethod
    def _cost( realization, interval, amount = Decimal( '20' ) ):
        return VehicleRunningCost(
            name = 'Fuel', handle = 'gasoline', expense_tax_class = ExpenseTaxClass.LIVING,
            interval = interval, amount = amount, realization = realization )

    @staticmethod
    def _vehicle_possession( handle ):
        return AssetProfile( handle = handle, name = 'Car', asset_class = AssetClass.DEPRECIATING,
                             opening_value = Decimal( '20000' ) )

    def test_smooth_cost_is_one_annualized_stream_per_vehicle( self ):
        # $20/car/week annualized x 52 = $1,040/yr, one stream per vehicle, each in its own window.
        v1 = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                       purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        v2 = _vehicle( 'vehicle-2', date( 2028, 1, 1 ), end_date = date( 2035, 1, 1 ),
                       purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        streams, items = self._run(
            self._plans( [ v1, v2 ], self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ) )
        self.assertEqual( items, [] )
        self.assertEqual( len( streams ), 2 )
        self.assertEqual( streams[ 0 ].amounts.segments[ 0 ].amount, Decimal( '1040' ) )   # per car, not scaled
        self.assertEqual( streams[ 0 ].window, DateWindow( start = date( 2026, 1, 1 ) ) )
        self.assertEqual( streams[ 1 ].window, DateWindow( start = date( 2028, 1, 1 ), end = date( 2035, 1, 1 ) ) )

    def test_discrete_cost_is_an_item_per_vehicle_at_its_cadence( self ):
        semiannual = Duration( 6, TimeUnit.MONTH )
        vehicle = _vehicle( 'vehicle-1', date( 2026, 1, 1 ),
                            purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        streams, items = self._run(
            self._plans( [ vehicle ], self._cost( Realization.DISCRETE, semiannual, Decimal( '750' ) ) ) )
        self.assertEqual( streams, [] )
        self.assertEqual( items[ 0 ].cadence.interval, semiannual )
        self.assertEqual( items[ 0 ].amounts.segments[ 0 ].amount, Decimal( '750' ) )   # per car

    def test_a_leased_vehicle_accrues_running_costs_over_its_lease( self ):
        # Regression: a current leased vehicle is operated over its lease term and accrues running costs
        # even when its end-of-term successor is unfinished -- its window comes from the lease it holds
        # now, not from the whole plan being complete. (A net-new lease already counted; this restores the
        # current-lease parity that the atomic-disposition change had dropped.)
        renew = LeasedVehicleDisposition(
            vehicle_handle = 'lease-1', monthly = Decimal( '400' ), lease_end = date( 2030, 1, 1 ),
            kind = LeaseDispositionKind.RENEW,
            successor = Vehicle( handle = '', payment_method = PaymentMethod.LEASE ) )   # unfinished
        self.assertFalse( renew.is_complete )
        plans = Plans( vehicle_plan = VehiclePlan(
            leased_dispositions = [ renew ],
            running_costs = [ self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ] ) )
        streams, _items = self._run( plans )
        self.assertEqual( len( streams ), 1 )                                        # the operated lease
        self.assertEqual( streams[ 0 ].window,
                          DateWindow( start = date( 2026, 1, 1 ), end = date( 2029, 12, 31 ) ) )

    def test_a_lease_missing_its_monthly_accrues_no_running_costs( self ):
        # A lease still missing its monthly (its required, defining cost) is not yet a real lease: it
        # accrues no running costs, matching the monthly item it also does not emit. The window and the
        # payment gate alike on the monthly, so an incomplete lease never leaks a running-costs-only partial.
        no_monthly = LeasedVehicleDisposition(
            vehicle_handle = 'lease-1', lease_end = date( 2030, 1, 1 ),
            kind = LeaseDispositionKind.RETURN )                       # lease_end set, monthly blank
        plans = Plans( vehicle_plan = VehiclePlan(
            leased_dispositions = [ no_monthly ],
            running_costs = [ self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ] ) )
        self.assertEqual( self._run( plans ), ( [], [] ) )

    def test_a_current_vehicle_possession_is_run_from_the_start( self ):
        # The fix: a car owned today (a DEPRECIATING possession) incurs running costs from the forecast
        # start over an open window -- previously it counted for nothing until a planned purchase. A
        # non-vehicle possession (a collectible) is not a car and is excluded.
        profile = Profile( assets = [
            self._vehicle_possession( 'possession-1' ),
            AssetProfile( handle = 'possession-2', name = 'Ring', asset_class = AssetClass.COLLECTIBLES,
                          opening_value = Decimal( '5000' ) ) ] )
        streams, _items = self._run(
            self._plans( [], self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ),
            profile = profile )
        self.assertEqual( len( streams ), 1 )              # only the vehicle, not the collectible
        self.assertEqual( streams[ 0 ].window, DateWindow( start = date( 2026, 1, 1 ) ) )

    def test_a_sold_possession_stops_the_day_before_its_sale( self ):
        # A current car replaced/sold stops incurring running costs at the sale -- its window ends the day
        # before, so it does not double-count with the replacement that begins on the sale date.
        streams, _items = self._run(
            self._plans( [], self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ),
            profile = Profile( assets = [ self._vehicle_possession( 'possession-1' ) ] ),
            sale_dates = { 'possession-1' : date( 2030, 1, 1 ) } )
        self.assertEqual( streams[ 0 ].window,
                          DateWindow( start = date( 2026, 1, 1 ), end = date( 2029, 12, 31 ) ) )

    def test_a_possession_sold_on_the_start_date_accrues_nothing( self ):
        # A car sold exactly on the forecast start is operated for zero days: its window ends the day
        # before it begins (inverted), which covers no date, so the engine draws nothing from it.
        streams, _items = self._run(
            self._plans( [], self._cost( Realization.SMOOTH, Duration( 1, TimeUnit.WEEK ) ) ),
            profile = Profile( assets = [ self._vehicle_possession( 'possession-1' ) ] ),
            sale_dates = { 'possession-1' : date( 2026, 1, 1 ) } )        # sold on the run's start
        self.assertFalse( streams[ 0 ].window.covers( date( 2026, 1, 1 ) ) )   # covers nothing -> zero cost

    def test_blank_amount_or_no_vehicle_yields_nothing( self ):
        weekly  = Duration( 1, TimeUnit.WEEK )
        vehicle = _vehicle( 'vehicle-1', date( 2026, 1, 1 ) )
        self.assertEqual(                                  # a blank per-car amount is not charged
            self._run( self._plans( [ vehicle ], self._cost( Realization.SMOOTH, weekly, None ) ) ),
            ( [], [] ) )
        self.assertEqual(                                  # no vehicles at all -> nothing to apply
            self._run( self._plans( [], self._cost( Realization.SMOOTH, weekly ) ) ),
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
