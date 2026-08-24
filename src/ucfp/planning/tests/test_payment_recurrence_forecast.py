"""A recurring Payment expands across its date window in the engine (#210 Phase 2).

Phase 2's claim is that a recurring payment needs no engine change: a recurring `ExpenseItem` over a
`[date, finish]` window is already expanded by the forecast. This test proves that end to end -- a payment
recurring yearly over a four-year window books its expense in each of those years and nowhere else -- so a
regression in the materialized cadence/window (or a mistaken belief the engine expands it) is caught.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import PlanEvent, Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.materialization import ForecastFrame, materialize


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
                          opening_value = Decimal( '1000000' ), cost_basis = Decimal( '1000000' ) ),
            AssetProfile( handle = 'stocks', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '200000' ), cost_basis = Decimal( '200000' ) ),
            AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                          opening_value = Decimal( '100000' ), cost_basis = Decimal( '100000' ) ) ] )


def _recurring_payment( interval, finish, inflation_indexed = True ) -> Plans:
    event = PlanEvent(
        kind = EventKind.GENERAL_PAYMENT, date = date( 2032, 8, 1 ), amount = Decimal( '40000' ),
        label = 'College Tuition', interval = interval, finish = finish,
        inflation_indexed = inflation_indexed )
    return Plans( events = [ event ] )


class RecurringPaymentForecastTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()

    def _tuition_by_year( self, plans : Plans ) -> dict:
        """Total debited to the College Tuition expense account, keyed by calendar year."""
        frame = ForecastFrame(
            start_date = date( 2030, 1, 1 ), end_date = date( 2040, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        books   = Forecast( materialize(
            profile = _profile(), plans = plans, assumptions = _assumptions(), frame = frame ) ).run().books
        tuition = { a for a in books.accounts if a.name == 'College Tuition' }
        by_year : dict = dict()
        for txn in books.transactions:
            for entry in txn.entries:
                if entry.account in tuition:
                    year = txn.transaction_date.year
                    by_year[ year ] = by_year.get( year, Decimal( 0 ) ) + entry.amount
        return by_year

    def test_a_yearly_payment_books_in_each_window_year_and_no_other( self ):
        by_year = self._tuition_by_year(
            _recurring_payment( Duration( 1, TimeUnit.YEAR ), date( 2035, 8, 1 ) ) )
        self.assertEqual( set( by_year ), { 2032, 2033, 2034, 2035 } )   # inclusive window, once per year

    def test_a_biennial_payment_books_only_on_its_cadence( self ):
        # Every 2 years anchored at 2032 -> 2032 and 2034 fall in [2032, 2035]; 2033/2035 do not.
        by_year = self._tuition_by_year(
            _recurring_payment( Duration( 2, TimeUnit.YEAR ), date( 2035, 8, 1 ) ) )
        self.assertEqual( set( by_year ), { 2032, 2034 } )

    def test_a_one_time_payment_books_a_single_year( self ):
        by_year = self._tuition_by_year( _recurring_payment( None, None ) )
        self.assertEqual( set( by_year ), { 2032 } )

    def test_a_fixed_payment_books_its_entered_amount_unchanged_each_year( self ):
        # inflation_indexed=False -> each occurrence books the entered $40,000 as-is, no inflation growth.
        by_year = self._tuition_by_year( _recurring_payment(
            Duration( 1, TimeUnit.YEAR ), date( 2035, 8, 1 ), inflation_indexed = False ) )
        self.assertEqual( set( by_year ), { 2032, 2033, 2034, 2035 } )
        for year, amount in by_year.items():
            self.assertEqual( amount, Decimal( '40000' ), f'year {year} should be the entered amount' )

    def test_an_indexed_payment_grows_year_over_year( self ):
        # The inflation-indexed default grows the today's-dollar $40,000 to each year's nominal figure
        # (from the 2030 forecast start), so every occurrence exceeds the entered amount and later ones
        # exceed earlier ones -- the very growth the fixed option removes.
        by_year = self._tuition_by_year( _recurring_payment(
            Duration( 1, TimeUnit.YEAR ), date( 2035, 8, 1 ), inflation_indexed = True ) )
        self.assertGreater( by_year[ 2032 ], Decimal( '40000' ) )      # already grown from the 2030 start
        self.assertGreater( by_year[ 2035 ], by_year[ 2032 ] )         # and keeps growing
