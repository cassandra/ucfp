"""Run-table rollup: a vehicle's every account groups under one per-vehicle column (#149 Part 1).

A financed vehicle mints a fresh loan, interest, and holding account for every replacement cycle it runs
through. Left alone they proliferate as duplicate sibling columns keyed by reminted UUIDs. `display_placement`
stamping resolves each back to its `vehicle-N` root and groups them: loans under a Vehicle Loans surface,
interest under a Vehicle rung of the Non-deductible Interest class, holdings under a top-level Vehicles
pane -- so a vehicle's succession of accounts renders as one drillable column instead of a spray of them.

These tests run a full forecast (real handles, real reminted UUIDs) over a current financed vehicle that a
Replace turns over across the horizon, so each axis carries several accounts to roll up.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books_table import BooksColumnKey, BooksSummaryColumn, BooksTableColumnCatalog
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.enums import PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LoanRepayment, Plans, Vehicle, VehicleDisposition, VehiclePlan )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, LeasedVehicle, Profile, SubjectProfile
from ucfp.inputs.vehicle_handles import is_vehicle_loan_handle, is_vehicle_loan_interest_handle
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.display_placement import (
    _UNMAPPED_ORDER, _VehicleRung, _vehicle_group, _vehicle_rungs, stamp_display_placements )
from ucfp.planning.materialization import ForecastFrame, materialize

_VEHICLE_LOANS_KEY  = 'class:LIABILITY:vehicle-loans'
_VEHICLE_1_LOAN_KEY = _VEHICLE_LOANS_KEY + '/vehicle-loan-vehicle-1'
_VEHICLES_PANE_KEY  = 'class:ASSET:pane-vehicles'


def _assumptions() -> Assumptions:
    return Assumptions(
        economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


def _profile() -> Profile:
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                          opening_value = Decimal( '300000' ), cost_basis = Decimal( '300000' ) ),
            AssetProfile( handle = 'stocks', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '200000' ), cost_basis = Decimal( '200000' ) ),
            AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                          opening_value = Decimal( '100000' ), cost_basis = Decimal( '100000' ) ) ] )


def _with_financed_vehicle( profile : Profile, handle : str, name : str ) -> Profile:
    """`profile` plus one owned, financed current vehicle -- a DEPRECIATING holding and the `AUTO` `Debt`
    secured against it (`{handle}-loan`)."""
    return replace(
        profile,
        assets = profile.assets + [ AssetProfile(
            handle = handle, name = name, asset_class = AssetClass.DEPRECIATING,
            opening_value = Decimal( '20000' ) ) ],
        debts = profile.debts + [ Debt(
            handle = f'{handle}-loan', name = f'{name} loan', kind = DebtKind.AUTO,
            balance = Decimal( '18000' ), secured_asset = handle ) ] )


def _replace_disposition( handle : str, name : str ) -> VehicleDisposition:
    """A Replace of `handle` in 2029 by a recurring successor (financed, replaced every 5 years), so the
    horizon carries the current loan, its payoff, and several replacement-cycle loans -- all one root."""
    successor = Vehicle(
        handle = '', name = name, purchase_price = Decimal( '32000' ), recurrence_years = 5,
        payment_method = PaymentMethod.LOAN, down_payment = Decimal( '4000' ) )
    return VehicleDisposition(
        vehicle_handle = handle, kind = VehicleDispositionKind.REPLACE,
        sale_date = date( 2029, 1, 1 ), replacement = successor )


def _stamped( profile : Profile, plans : Plans ):
    """A forecast over `profile`/`plans`, stamped, returned as (books, column catalog)."""
    frame = ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2036, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )
    books = Forecast( materialize(
        profile = profile, plans = plans, assumptions = _assumptions(), frame = frame ) ).run().books
    stamp_display_placements( books, profile )
    return books, BooksTableColumnCatalog.build( Bookkeeper( books ).chart )


def _path_keys( account ) -> list:
    return [ group.key for group in account.display_placement.path ]


class VehicleRollupPlacementTest( TestCase ):
    """One financed current vehicle turned over by a Replace: its loan, interest, and holding accounts --
    current plus every replacement cycle -- each collapse onto a single per-vehicle rung."""

    def setUp( self ):
        seed_default_parameter_sets()

    def _run( self ):
        profile = _with_financed_vehicle( _profile(), 'vehicle-1', 'Civic' )
        plans   = Plans(
            loan_repayments = [ LoanRepayment(
                debt_handle = 'vehicle-1-loan', interest_rate = Rate.percent( Decimal( '5' ) ),
                remaining_term = Duration( 60, TimeUnit.MONTH ) ) ],
            vehicle_plan = VehiclePlan(
                dispositions = [ _replace_disposition( 'vehicle-1', 'Civic' ) ] ) )
        return _stamped( profile, plans )

    def test_every_loan_account_groups_under_one_vehicle_loans_rung( self ):
        books, _catalog = self._run()
        loans = [ a for a in books.accounts
                  if a.handle is not None and is_vehicle_loan_handle( str( a.handle ) ) ]
        self.assertGreaterEqual( len( loans ), 2, 'expected the current loan and its replacement cycles' )
        for account in loans:
            self.assertIsNotNone( account.display_placement, f'{account.handle} fell back (unstamped)' )
            self.assertEqual( _path_keys( account ), [ 'vehicle-loans', 'vehicle-loan-vehicle-1' ] )
        # The distinct accounts all resolve to one rung labelled by the vehicle -- the rollup itself.
        self.assertEqual(
            { tuple( _path_keys( a ) ) for a in loans }, { ( 'vehicle-loans', 'vehicle-loan-vehicle-1' ) } )
        self.assertEqual( loans[ 0 ].display_placement.path[ 1 ].label, 'Civic' )

    def test_every_interest_account_nests_under_non_deductible_interest_then_vehicle( self ):
        books, _catalog = self._run()
        interest = [ a for a in books.accounts
                     if a.handle is not None and is_vehicle_loan_interest_handle( str( a.handle ) ) ]
        self.assertGreaterEqual( len( interest ), 2 )
        for account in interest:
            self.assertIsNotNone( account.display_placement, f'{account.handle} fell back (unstamped)' )
            self.assertEqual(
                _path_keys( account ),
                [ 'NON_DEDUCTIBLE_INTEREST', 'vehicle-interest', 'vehicle-interest-vehicle-1' ] )

    def test_current_and_replacement_holdings_share_one_vehicle_rung( self ):
        books, catalog = self._run()
        holdings = [ a for a in books.accounts if a.asset_class is AssetClass.DEPRECIATING ]
        self.assertGreaterEqual( len( holdings ), 2, 'expected the current holding and its replacement(s)' )
        for account in holdings:
            self.assertEqual(
                _path_keys( account ), [ 'pane-vehicles', 'holding-vehicle-vehicle-1' ] )
        # And at the catalog level: the several holdings roll into one Vehicles-pane column per vehicle.
        vehicle_column = catalog.get( BooksColumnKey( _VEHICLES_PANE_KEY + '/holding-vehicle-vehicle-1' ) )
        self.assertIsInstance( vehicle_column, BooksSummaryColumn )
        self.assertEqual( len( vehicle_column.member_keys ), len( holdings ) )

    def test_the_catalog_rolls_the_loans_into_one_vehicle_loans_column( self ):
        books, catalog = self._run()
        loans = [ a for a in books.accounts
                  if a.handle is not None and is_vehicle_loan_handle( str( a.handle ) ) ]
        surface = catalog.get( BooksColumnKey( _VEHICLE_LOANS_KEY ) )
        self.assertIsNotNone( surface, 'no Vehicle Loans surface column formed' )
        self.assertIsInstance( surface, BooksSummaryColumn )
        # The surface holds a single child -- the per-vehicle rung -- which in turn gathers every reminted
        # loan UUID: N accounts collapse onto one drillable per-vehicle column, not N sibling columns.
        self.assertEqual( surface.member_keys, ( BooksColumnKey( _VEHICLE_1_LOAN_KEY ), ) )
        vehicle_column = catalog.get( BooksColumnKey( _VEHICLE_1_LOAN_KEY ) )
        self.assertIsInstance( vehicle_column, BooksSummaryColumn )
        self.assertEqual( len( vehicle_column.member_keys ), len( loans ) )


class MultiVehicleRollupPlacementTest( TestCase ):
    """Two financed vehicles keep separate per-vehicle rungs under the shared Vehicle Loans surface -- the
    rollup groups a vehicle's own accounts, it does not merge distinct vehicles."""

    def setUp( self ):
        seed_default_parameter_sets()

    def test_two_vehicles_get_distinct_rungs_under_one_surface( self ):
        profile = _with_financed_vehicle(
            _with_financed_vehicle( _profile(), 'vehicle-1', 'Civic' ), 'vehicle-2', 'Tesla' )
        plans   = Plans( loan_repayments = [
            LoanRepayment( debt_handle = 'vehicle-1-loan', interest_rate = Rate.percent( Decimal( '5' ) ),
                           remaining_term = Duration( 60, TimeUnit.MONTH ) ),
            LoanRepayment( debt_handle = 'vehicle-2-loan', interest_rate = Rate.percent( Decimal( '6' ) ),
                           remaining_term = Duration( 48, TimeUnit.MONTH ) ) ] )
        books, catalog = _stamped( profile, plans )
        by_root = { tuple( _path_keys( a ) )
                    for a in books.accounts
                    if a.handle is not None and is_vehicle_loan_handle( str( a.handle ) ) }
        self.assertEqual( by_root, {
            ( 'vehicle-loans', 'vehicle-loan-vehicle-1' ),
            ( 'vehicle-loans', 'vehicle-loan-vehicle-2' ) } )
        # At the catalog level: one shared surface, two distinct per-vehicle child columns under it.
        surface = catalog.get( BooksColumnKey( _VEHICLE_LOANS_KEY ) )
        self.assertEqual(
            { key.token for key in surface.member_keys },
            { _VEHICLE_LOANS_KEY + '/vehicle-loan-vehicle-1',
              _VEHICLE_LOANS_KEY + '/vehicle-loan-vehicle-2' } )


class NoVehicleBooksTest( TestCase ):
    """A books with no vehicles leaves the vehicle passes as no-ops: no Vehicle Loans surface, no Vehicles
    pane, and every account keeps its ordinary placement."""

    def setUp( self ):
        seed_default_parameter_sets()

    def test_the_vehicle_columns_are_absent_without_any_vehicle( self ):
        _books, catalog = _stamped( _profile(), Plans() )       # _profile() has cash/stocks/bonds only
        self.assertIsNone( catalog.get( BooksColumnKey( _VEHICLE_LOANS_KEY ) ) )
        self.assertIsNone( catalog.get( BooksColumnKey( _VEHICLES_PANE_KEY ) ) )


class VehicleRungOrderingTest( SimpleTestCase ):
    """`_vehicle_rungs` orders the household's vehicles (owned holdings, then leased facts) and
    `_vehicle_group` falls back to the account's own name for a vehicle no current household vehicle roots."""

    def test_owned_then_leased_vehicles_are_ordered_and_named( self ):
        profile = Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [ AssetProfile( handle = 'vehicle-1', name = 'Civic',
                                     asset_class = AssetClass.DEPRECIATING,
                                     opening_value = Decimal( '20000' ) ) ],
            leased_vehicles = [ LeasedVehicle( handle = 'vehicle-2', name = 'Leased EV' ) ] )
        rungs = _vehicle_rungs( profile )
        self.assertEqual( rungs[ 'vehicle-1' ], _VehicleRung( 0, 'Civic' ) )       # owned first
        self.assertEqual( rungs[ 'vehicle-2' ], _VehicleRung( 1, 'Leased EV' ) )   # leased folds in after

    def test_a_net_new_vehicle_falls_back_to_its_account_name_at_the_tail( self ):
        # A plan-acquired vehicle no current household vehicle roots -- absent from `_vehicle_rungs`.
        group = _vehicle_group( 'vehicle-9', SimpleNamespace( name = 'New Truck' ), {}, 'vehicle-loan-' )
        self.assertEqual( group.key, 'vehicle-loan-vehicle-9' )
        self.assertEqual( group.label, 'New Truck' )
        self.assertEqual( group.order, _UNMAPPED_ORDER )
