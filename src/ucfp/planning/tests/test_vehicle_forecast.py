"""End-to-end: owned vehicles (cash and financed) materialize and run as real depreciating holdings.

Unlike the shape tests in `test_materialization`, these run a full forecast (materialize -> engine) to
confirm the vehicle model behaves. A CASH car is an owned holding that depreciates between purchases, each
replacement trades the old one in and buys the next, and buying it is a cash -> asset swap (not a
sticker-price expense). A LOAN car is the same owned, depreciating holding financed by a real recurring
loan: each cycle originates an auto-loan that amortizes on the books, and the outgoing car's loan is paid
off at trade-in.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import ScheduledLoanPayoff
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.enums import PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LoanRepayment, Plans, Vehicle, VehicleDisposition, VehiclePlan, VehicleRunningCost )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant, Realization
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.materialization import ForecastFrame, materialize

_HOLDING = 'vehicle:vehicle-1'


def _profile() -> Profile:
    # Cash funds the car; Stocks/Bonds are the default drawdown's sweep homes (present in both the with-
    # and without-car runs, so their growth cancels in the net-worth comparison).
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                          opening_value = Decimal( '200000' ), cost_basis = Decimal( '200000' ) ),
            AssetProfile( handle = 'stocks', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '200000' ), cost_basis = Decimal( '200000' ) ),
            AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                          opening_value = Decimal( '100000' ), cost_basis = Decimal( '100000' ) ) ] )


def _assumptions() -> Assumptions:
    # Pin inflation to a fixed 2.5% so the price-indexing expectations below (each `x 1.025`) hold
    # independently of the seeded EXPECTED default, which is free to change. Everything else -- notably
    # the 18% vehicle depreciation -- is inherited from the seed.
    economics = replace(
        economic_parameters( EconomicOutlookVariant.EXPECTED.label ), inflation = Rate( Decimal( '0.025' ) ) )
    return Assumptions(
        economics = economics,
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


def _run( plans : Plans ) -> Bookkeeper:
    frame = ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2034, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )
    books = Forecast( materialize(
        profile = _profile(), plans = plans, assumptions = _assumptions(), frame = frame ) ).run().books
    return Bookkeeper( books )


def _vehicle_plans( method : PaymentMethod, **fields ) -> Plans:
    car = Vehicle(
        handle = 'vehicle-1', name = 'Car', purchase_date = date( 2027, 1, 1 ),
        purchase_price = Decimal( '30000' ), recurrence_years = 5, payment_method = method, **fields )
    return Plans( vehicle_plan = VehiclePlan( vehicles = [ car ] ) )


class CashVehicleForecastTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )        # the EXPECTED outlook (18% depreciation) is seeded

    def _reader( self, *, with_vehicle : bool ) -> Bookkeeper:
        return _run( _vehicle_plans( PaymentMethod.CASH ) if with_vehicle else Plans() )

    def test_cash_vehicle_is_an_owned_holding_that_depreciates( self ):
        # Depreciation applies at each year's start on the opening value, so the car sits at its (inflation-
        # indexed) purchase price the year it is bought (2027) and erodes from the next year on.
        reader  = self._reader( with_vehicle = True )
        holding = reader.chart.account( _HOLDING )
        self.assertEqual( holding.asset_class, AssetClass.DEPRECIATING )
        reader.assert_balanced()
        bought = reader.ledger.market_value( holding, through = date( 2027, 12, 31 ) )
        later  = reader.ledger.market_value( holding, through = date( 2031, 12, 31 ) )
        self.assertEqual( bought, Decimal( '30750' ) )     # 30,000 x 1.025 (a year's inflation); not yet down
        self.assertLess( later, Decimal( '25000' ) )       # several years of ~18%/yr decline
        self.assertGreater( later, Decimal( '0' ) )

    def test_replacement_trades_in_and_rebuys( self ):
        reader  = self._reader( with_vehicle = True )
        holding = reader.chart.account( _HOLDING )
        before  = reader.ledger.market_value( holding, through = date( 2031, 12, 31 ) )   # 4-yr-old car
        after   = reader.ledger.market_value( holding, through = date( 2032, 12, 31 ) )   # replaced in 2032
        self.assertLess( before, Decimal( '20000' ) )      # well depreciated before the swap
        self.assertGreater( after, before )                # fresh again after the trade-in...
        self.assertGreater( after, Decimal( '30750' ) )    # ...and dearer than the 2027 car (more inflation)

    def test_replacements_track_inflation_over_the_horizon( self ):
        # The point of routing replacements through the engine: a later car costs more. The 2027 buy is one
        # year of inflation above sticker; the 2032 replacement, several more -- no flat price over the run.
        reader     = self._reader( with_vehicle = True )
        holding    = reader.chart.account( _HOLDING )
        fresh_2027 = reader.ledger.market_value( holding, through = date( 2027, 12, 31 ) )   # just bought
        fresh_2032 = reader.ledger.market_value( holding, through = date( 2032, 12, 31 ) )   # just replaced
        self.assertEqual( fresh_2027, Decimal( '30750' ) )                 # 30,000 x 1.025
        self.assertGreater( fresh_2032, fresh_2027 )                       # 30,000 x 1.025^6, dearer

    def test_buying_for_cash_is_a_swap_not_a_sticker_expense( self ):
        # In the purchase year, buying the car just moves cash into an asset -- net worth is unchanged
        # versus not buying it. An expense lump would instead drop net worth by the whole $30,000.
        with_car    = self._reader( with_vehicle = True ).ledger.net_worth( through = date( 2027, 12, 31 ) )
        without_car = self._reader( with_vehicle = False ).ledger.net_worth( through = date( 2027, 12, 31 ) )
        self.assertAlmostEqual( with_car, without_car, delta = Decimal( '1000' ) )


class FinancedVehicleForecastTest( TestCase ):
    """A LOAN car is the same owned, depreciating holding, financed by a real recurring loan that
    amortizes on the books; each replacement pays off the outgoing loan and originates the next."""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def _reader( self ) -> Bookkeeper:
        # $30k car, $5k down -> a $25k auto-loan each cycle, replaced every 5 years from 2027.
        return _run( _vehicle_plans( PaymentMethod.LOAN, down_payment = Decimal( '5000' ) ) )

    def test_financing_creates_a_real_amortizing_loan_with_interest( self ):
        reader = self._reader()
        reader.assert_balanced()
        loan     = reader.chart.account( 'vehicle-loan:vehicle-1:0' )        # originated at the 2027 buy
        interest = reader.chart.account( 'vehicle-loan-interest:vehicle-1:0' )
        balance  = reader.ledger.natural_balance( loan, through = date( 2028, 12, 31 ) )
        self.assertGreater( balance, Decimal( '0' ) )                        # a real liability...
        self.assertLess( balance, Decimal( '25000' ) )                       # ...amortizing down from $25k
        self.assertGreater( reader.ledger.natural_balance( interest ), Decimal( '0' ) )   # interest charged

    def test_financed_car_is_a_depreciating_holding_like_cash( self ):
        reader  = self._reader()
        holding = reader.chart.account( _HOLDING )
        self.assertEqual( holding.asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( reader.ledger.market_value( holding, through = date( 2027, 12, 31 ) ),
                          Decimal( '30750' ) )                               # bought at the inflated price
        self.assertLess( reader.ledger.market_value( holding, through = date( 2031, 12, 31 ) ),
                         Decimal( '25000' ) )                                # then depreciates

    def test_replacement_reoriginates_a_fresh_loan( self ):
        reader = self._reader()
        # The 2027 loan (5-yr term) is retired by the 2032 replacement, which originates the next cycle's.
        self.assertEqual(
            reader.ledger.natural_balance( reader.chart.account( 'vehicle-loan:vehicle-1:0' ),
                                           through = date( 2033, 12, 31 ) ), Decimal( '0' ) )
        self.assertGreater(
            reader.ledger.natural_balance( reader.chart.account( 'vehicle-loan:vehicle-1:1' ),
                                           through = date( 2033, 12, 31 ) ), Decimal( '0' ) )

    def test_each_cycles_loan_principal_inflates_with_the_price( self ):
        # The financed principal tracks the inflated price, so a later cycle's loan is larger -- the debt
        # half moves with the asset half instead of staying flat. Read each loan's balance just after its
        # origination (before amortization), which is its principal.
        reader = self._reader()
        first  = reader.ledger.natural_balance( reader.chart.account( 'vehicle-loan:vehicle-1:0' ),
                                                through = date( 2027, 1, 1 ) )
        second = reader.ledger.natural_balance( reader.chart.account( 'vehicle-loan:vehicle-1:1' ),
                                                through = date( 2032, 1, 1 ) )
        self.assertEqual( first, Decimal( '25625' ) )      # (30,000 - 5,000) x 1.025
        self.assertGreater( second, first )                # x 1.025^6, a larger principal

    def test_a_financed_purchase_costs_cash_only_the_down_payment( self ):
        # The borrow offsets the purchase in the same span, so the 2027 buy costs cash only its down
        # payment -- (30,000 - 25,000) inflated -- not the full 30,750 price; the asset+debt pairing nets.
        through     = date( 2027, 1, 1 )
        with_car    = self._reader()
        without_car = _run( Plans() )
        spent = ( without_car.ledger.market_value( without_car.chart.account( 'cash' ), through = through )
                  - with_car.ledger.market_value( with_car.chart.account( 'cash' ), through = through ) )
        self.assertEqual( spent, Decimal( '5125' ) )       # down = (30,000 - 25,000) x 1.025, not 30,750


# --- Current (owned) vehicle loans -----------------------------------------

def _run_with( profile : Profile, plans : Plans ) -> Bookkeeper:
    """Like `_run`, but over a caller-supplied profile (the current-vehicle tests add an owned car)."""
    frame = ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2036, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )
    return Bookkeeper( Forecast( materialize(
        profile = profile, plans = plans, assumptions = _assumptions(), frame = frame ) ).run().books )


def _financed_current_profile() -> Profile:
    """A base run profile plus one owned, financed current vehicle -- a DEPRECIATING holding and the `AUTO`
    `Debt` secured against it (handle `vehicle-1-loan`)."""
    base = _profile()
    return replace(
        base,
        assets = base.assets + [ AssetProfile(
            handle = 'vehicle-1', name = 'Civic', asset_class = AssetClass.DEPRECIATING,
            opening_value = Decimal( '20000' ) ) ],
        debts = [ Debt( handle = 'vehicle-1-loan', name = 'Civic loan', kind = DebtKind.AUTO,
                        balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )


def _current_loan_plans( disposition : VehicleDisposition ) -> Plans:
    """A current vehicle loan (5%, 60 months on `vehicle-1-loan`) plus one disposition for it."""
    return Plans(
        loan_repayments = [ LoanRepayment(
            debt_handle = 'vehicle-1-loan', interest_rate = Rate.percent( Decimal( '5' ) ),
            remaining_term = Duration( 60, TimeUnit.MONTH ) ) ],
        vehicle_plan = VehiclePlan( dispositions = [ disposition ] ) )


class CurrentVehicleLoanForecastTest( TestCase ):
    """A current owned vehicle's auto loan materializes vehicle-scoped and behaves end to end: it amortizes
    under `vehicle-loan:{v}`, its sale pays it off (the positive payoff path the no-op guard exists beside),
    and a Replace keeps the current loan and its successor's recurring loan under distinct handles."""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def test_a_sold_financed_vehicles_loan_amortizes_then_is_paid_off( self ):
        reader = _run_with( _financed_current_profile(), _current_loan_plans( VehicleDisposition(
            vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
            sale_date = date( 2029, 1, 1 ) ) ) )
        reader.assert_balanced()
        loan = reader.chart.account( 'vehicle-loan:vehicle-1' )       # materialized vehicle-scoped
        self.assertIsNotNone( loan )
        self.assertGreater( reader.ledger.natural_balance( loan, through = date( 2028, 12, 31 ) ),
                            Decimal( '0' ) )                          # owing before the sale
        self.assertEqual( reader.ledger.natural_balance( loan, through = date( 2030, 12, 31 ) ),
                          Decimal( '0' ) )                            # the sale paid it off

    def test_a_replace_keeps_the_current_loan_and_its_successor_distinct( self ):
        successor = Vehicle(
            handle = '', name = 'Civic', purchase_price = Decimal( '32000' ), recurrence_years = 5,
            payment_method = PaymentMethod.LOAN, down_payment = Decimal( '4000' ) )
        params = materialize(
            profile = _financed_current_profile(),
            plans   = _current_loan_plans( VehicleDisposition(
                vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                sale_date = date( 2029, 1, 1 ), replacement = successor ) ),
            assumptions = _assumptions(),
            frame = ForecastFrame( start_date = date( 2026, 1, 1 ), end_date = date( 2036, 12, 31 ),
                                   granularity = Duration( 1, TimeUnit.YEAR ) ) )
        current_loans = { loan.handle for loan in params.loans }
        originations  = { origination.handle for origination in params.recurring_loan_originations }
        payoffs       = { event.loan for event in params.events if isinstance( event, ScheduledLoanPayoff ) }
        self.assertIn( 'vehicle-loan:vehicle-1', current_loans )                   # the current loan (t0)
        self.assertIn( 'vehicle-loan:vehicle-1-replacement', originations )    # successor's recurring loan
        self.assertNotIn( 'vehicle-loan:vehicle-1', originations )                 # distinct -- no collision
        self.assertIn( 'vehicle-loan:vehicle-1', payoffs )                         # the sale pays it off


class RunningCostAcrossReplacementTest( TestCase ):
    """A discrete (semi-annual) running cost bills on one fleet-wide schedule, so replacing a vehicle
    mid-year splits that year's billing between the outgoing and incoming car instead of billing both in
    full. The year's total tracks the number of cars operated, not the number of changeovers -- a
    regression guard for the cadence-phase double-count that made a replacement year charge ~1.5x."""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    @staticmethod
    def _insurance() -> VehicleRunningCost:
        # Semi-annual: a mis-phased changeover would surface as an extra occurrence in the swap year.
        return VehicleRunningCost(
            name = 'Insurance', handle = 'vehicle-insurance', expense_tax_class = ExpenseTaxClass.LIVING,
            interval = Duration( 6, TimeUnit.MONTH ), amount = Decimal( '600' ),
            realization = Realization.DISCRETE )

    def _insurance_2034( self, plans : Plans ) -> Decimal:
        reader  = _run_with( _financed_current_profile(), plans )
        account = next( a for a in reader.chart.accounts() if a.name == 'Insurance' )
        return sum( ( posting.signed_amount for posting in reader.postings( account )
                      if posting.date.year == 2034 ), Decimal( '0' ) )

    def test_a_mid_year_replacement_does_not_inflate_the_years_running_cost( self ):
        repay = [ LoanRepayment(
            debt_handle = 'vehicle-1-loan', interest_rate = Rate.percent( Decimal( '5' ) ),
            remaining_term = Duration( 60, TimeUnit.MONTH ) ) ]
        kept = self._insurance_2034( Plans(
            loan_repayments = repay,
            vehicle_plan = VehiclePlan( running_costs = [ self._insurance() ] ) ) )
        replaced = self._insurance_2034( Plans(
            loan_repayments = repay,
            vehicle_plan = VehiclePlan(
                running_costs = [ self._insurance() ],
                dispositions  = [ VehicleDisposition(
                    vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                    sale_date = date( 2034, 7, 1 ),
                    replacement = Vehicle(
                        handle = '', name = 'Civic', purchase_price = Decimal( '32000' ),
                        recurrence_years = 5, payment_method = PaymentMethod.LOAN,
                        down_payment = Decimal( '4000' ) ) ) ] ) ) )
        self.assertLess( kept, Decimal( '0' ) )        # the cost actually posted...
        self.assertEqual( replaced, kept )             # ...and the swap year matches the kept year, not 1.5x
