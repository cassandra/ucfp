"""End-to-end: a CASH vehicle materializes and runs as a real depreciating holding.

Unlike the shape tests in `test_materialization`, these run a full forecast (materialize -> engine) to
confirm the cash-vehicle model behaves: the car is an owned holding that depreciates between purchases,
each replacement trades the old one in and buys the next (its value jumps back up), and buying it is a
cash -> asset swap -- so it does not drop net worth by the sticker price the way expensing it would.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import Plans, Vehicle, VehiclePlan
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.materialization import ForecastFrame, materialize

_HOLDING = 'vehicle:vehicle-1'


class CashVehicleForecastTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )        # the EXPECTED outlook (18% depreciation) is seeded

    def _profile( self ) -> Profile:
        # Cash funds the car; Stocks/Bonds are the default drawdown's sweep homes (present in both the
        # with- and without-car runs, so their growth cancels in the net-worth comparison).
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

    def _assumptions( self ) -> Assumptions:
        return Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )

    def _plans( self, *, with_vehicle : bool ) -> Plans:
        if not with_vehicle:
            return Plans()
        car = Vehicle(
            handle = 'vehicle-1', name = 'Car', purchase_date = date( 2027, 1, 1 ),
            purchase_price = Decimal( '30000' ), recurrence_years = 5,
            payment_method = PaymentMethod.CASH )
        return Plans( vehicle_plan = VehiclePlan( vehicles = [ car ] ) )

    def _reader( self, *, with_vehicle : bool ) -> Bookkeeper:
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2034, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        books = Forecast( materialize(
            profile = self._profile(), plans = self._plans( with_vehicle = with_vehicle ),
            assumptions = self._assumptions(), frame = frame ) ).run().books
        return Bookkeeper( books )

    def test_cash_vehicle_is_an_owned_holding_that_depreciates( self ):
        # Depreciation applies at each year's start on the opening value, so the car sits at its full
        # price the year it is bought (2027) and erodes from the next year on.
        reader  = self._reader( with_vehicle = True )
        holding = reader.chart.account( _HOLDING )
        self.assertEqual( holding.asset_class, AssetClass.DEPRECIATING )
        reader.assert_balanced()
        bought = reader.ledger.market_value( holding, through = date( 2027, 12, 31 ) )
        later  = reader.ledger.market_value( holding, through = date( 2031, 12, 31 ) )
        self.assertEqual( bought, Decimal( '30000' ) )     # bought this year; not yet depreciated
        self.assertLess( later, Decimal( '25000' ) )       # several years of ~18%/yr decline
        self.assertGreater( later, Decimal( '0' ) )

    def test_replacement_trades_in_and_rebuys( self ):
        reader  = self._reader( with_vehicle = True )
        holding = reader.chart.account( _HOLDING )
        before  = reader.ledger.market_value( holding, through = date( 2031, 12, 31 ) )   # 4-yr-old car
        after   = reader.ledger.market_value( holding, through = date( 2032, 12, 31 ) )   # replaced in 2032
        self.assertLess( before, Decimal( '20000' ) )      # well depreciated before the swap
        self.assertEqual( after, Decimal( '30000' ) )      # the new car's value, fresh again

    def test_buying_for_cash_is_a_swap_not_a_sticker_expense( self ):
        # In the purchase year, buying the car just moves cash into an asset -- net worth is unchanged
        # versus not buying it. An expense lump would instead drop net worth by the whole $30,000.
        with_car    = self._reader( with_vehicle = True ).ledger.net_worth( through = date( 2027, 12, 31 ) )
        without_car = self._reader( with_vehicle = False ).ledger.net_worth( through = date( 2027, 12, 31 ) )
        self.assertAlmostEqual( with_car, without_car, delta = Decimal( '1000' ) )
