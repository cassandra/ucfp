"""End-to-end: selling the primary residence converts the household to a renter (draw-order Phase 3b).

Unlike the shape tests in `test_materialization` and the whitebox reaction in `test_property_sale_reaction`,
this runs a full forecast (materialize -> engine) so the whole chain is exercised: the thin sale event, the
shared sale routine (realize + closing costs + mortgage payoff), the reported sale, and the forecast's
one-time expense reconfiguration. Compared against an otherwise-identical no-sale run, the sale must end the
residence's ownership costs, carry its utilities, start rent, clear the mortgage, and realize the holding."""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.events import PROPERTY_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import LoanRepayment, PlanEvent, Plans, PropertyExpense
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant, ExpenseCategory, PropertyContext, Realization
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.display_placement import property_expense_handle
from ucfp.planning.materialization import ForecastFrame, _rent_account_handle, materialize

_SALE = date( 2033, 6, 1 )
_OWNED    = ( PropertyContext.RESIDENCE, PropertyContext.SECOND_HOME, PropertyContext.RENTAL )
_OCCUPIED = _OWNED + ( PropertyContext.RENTED_HOME, )


def _profile() -> Profile:
    # Ample cash so the plan never has a shortfall -- the sale is the *scheduled* one, not a forced auto-sale.
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1965, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                          opening_value = Decimal( '1500000' ), cost_basis = Decimal( '1500000' ) ),
            AssetProfile( handle = 'stocks', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '100000' ), cost_basis = Decimal( '100000' ) ),
            AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                          opening_value = Decimal( '100000' ), cost_basis = Decimal( '100000' ) ),
            AssetProfile( handle = 'residence', name = 'Home', asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
                          opening_value = Decimal( '500000' ), cost_basis = Decimal( '400000' ) ) ],
        debts = [ Debt( handle = 'mortgage', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                        balance = Decimal( '200000' ), secured_asset = 'residence' ) ] )


def _pexpense( name, handle, applies_to, amount ) -> PropertyExpense:
    return PropertyExpense(
        name = name, handle = handle, category = ExpenseCategory.UTILITIES_SERVICES,
        expense_tax_class = ExpenseTaxClass.LIVING, applies_to = applies_to,
        interval = Duration( 1, TimeUnit.MONTH ), realization = Realization.SMOOTH,
        default_amount = Decimal( amount ) )


def _plans( *, sell : bool ) -> Plans:
    events = [ PlanEvent( kind = EventKind.SELL_PROPERTY, date = _SALE,
                          selections = { PROPERTY_ROLE: 'residence' }, options = { 'rent_after': 'yes' } ) ] if sell else []
    return Plans(
        property_expenses = [
            _pexpense( 'Property Tax', 'property-tax', _OWNED, '400' ),   # own-only (ends at sale)
            _pexpense( 'Electric', 'electric', _OCCUPIED, '200' ),        # tenure-invariant (carries)
            _pexpense( 'Rent', 'rent', ( PropertyContext.RENTED_HOME, ), '2500' ) ],
        loan_repayments = [ LoanRepayment(
            debt_handle = 'mortgage', interest_rate = Rate.percent( Decimal( '6' ) ),
            remaining_term = Duration( 240, TimeUnit.MONTH ) ) ],
        events = events )


def _reader( plans : Plans ) -> Bookkeeper:
    frame = ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2040, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )
    result = Forecast( materialize(
        profile = _profile(), plans = plans,
        assumptions = Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) ),
        frame = frame ) ).run()
    reader = Bookkeeper( result.books )
    reader.assert_balanced()
    return reader


def _spent( reader : Bookkeeper, handle : str ) -> Decimal:
    account = reader.chart.account( handle )
    return reader.ledger.natural_balance( account ) if account is not None else Decimal( '0' )


class ResidenceSaleForecastTests( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.sold    = _reader( _plans( sell = True ) )
        self.no_sale = _reader( _plans( sell = False ) )
        self._own    = str( property_expense_handle( 'property-tax', 'residence' ) )
        self._util   = str( property_expense_handle( 'electric', 'residence' ) )
        self._rent   = _rent_account_handle( _plans( sell = True ) )

    def test_the_sale_starts_rent_and_stops_ownership_costs_but_carries_utilities( self ):
        self.assertLess( _spent( self.sold, self._own ), _spent( self.no_sale, self._own ) )   # own-costs end early
        self.assertEqual( _spent( self.sold, self._util ), _spent( self.no_sale, self._util ) )  # utilities carry
        self.assertGreater( _spent( self.sold, self._rent ), Decimal( '0' ) )                  # rent is billed
        self.assertEqual( _spent( self.no_sale, self._rent ), Decimal( '0' ) )                 # only after a sale

    def test_the_sale_realizes_the_residence_and_clears_the_mortgage( self ):
        self.assertEqual( self.sold.ledger.market_value( self.sold.chart.account( 'residence' ) ), Decimal( '0' ) )
        self.assertEqual( self.sold.ledger.natural_balance( self.sold.chart.account( 'mortgage' ) ), Decimal( '0' ) )
        self.assertGreater(                                                                    # the home is retained...
            self.no_sale.ledger.market_value( self.no_sale.chart.account( 'residence' ) ), Decimal( '0' ) )
