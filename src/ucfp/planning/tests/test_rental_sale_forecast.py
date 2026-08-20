"""End-to-end: selling a rental ends its rent and operating costs and recognizes its gain (draw-order 3b).

The rental counterpart of `test_residence_sale_forecast`: a full materialize-to-engine forecast of a
scheduled rental sale, checked against an otherwise identical no-sale run. The sale ends the rental's
income (books-driven, by its source-handle match) and its operating costs, clears the mortgage, realizes
the holding, and recognizes the sale gain (its accumulated depreciation recaptured within that class)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.events import PROPERTY_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import LoanRepayment, PlanEvent, Plans, PropertyExpense
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, IncomeFlow, Profile, PropertyProfile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant, ExpenseCategory, PropertyContext, Realization
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.display_placement import property_expense_handle
from ucfp.planning.materialization import ForecastFrame, materialize

_SALE = date( 2033, 6, 1 )


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
            AssetProfile( handle = 'rental', name = 'Rental', asset_class = AssetClass.REAL_ESTATE_RENTAL,
                          opening_value = Decimal( '500000' ), cost_basis = Decimal( '400000' ),
                          property = PropertyProfile(
                              acquisition_date = date( 2018, 1, 1 ), depreciable_basis = Decimal( '300000' ),
                              property_type = RealPropertyType.RESIDENTIAL ) ) ],
        debts = [ Debt( handle = 'mortgage', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                        balance = Decimal( '200000' ), secured_asset = 'rental' ) ],
        income_flows = [ IncomeFlow(
            handle = 'rent-income', name = 'Rent', subject_handle = None,
            income_tax_class = IncomeTaxClass.GROSS_RENTAL, amount = Decimal( '3000' ),
            interval = Duration( 1, TimeUnit.MONTH ), property_handle = 'rental' ) ] )


def _plans( *, sell : bool ) -> Plans:
    events = [ PlanEvent( kind = EventKind.SELL_PROPERTY, date = _SALE,
                          selections = { PROPERTY_ROLE: 'rental' } ) ] if sell else []
    return Plans(
        property_expenses = [ PropertyExpense(
            name = 'Maintenance', handle = 'maintenance', category = ExpenseCategory.UTILITIES_SERVICES,
            expense_tax_class = ExpenseTaxClass.RENTAL_EXPENSE, applies_to = ( PropertyContext.RENTAL, ),
            interval = Duration( 1, TimeUnit.MONTH ), realization = Realization.SMOOTH,
            default_amount = Decimal( '500' ) ) ],
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


def _balance( reader : Bookkeeper, account ) -> Decimal:
    return reader.ledger.natural_balance( account ) if account is not None else Decimal( '0' )


class RentalSaleForecastTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.sold    = _reader( _plans( sell = True ) )
        self.no_sale = _reader( _plans( sell = False ) )

    def _rent_income( self, reader ) -> Decimal:
        return _balance( reader, reader.chart.income_account( IncomeTaxClass.GROSS_RENTAL ) )

    def _operating( self, reader ) -> Decimal:
        return _balance( reader, reader.chart.account( str( property_expense_handle( 'maintenance', 'rental' ) ) ) )

    def test_the_sale_ends_the_rental_income_and_operating_costs( self ):
        self.assertLess( self._rent_income( self.sold ), self._rent_income( self.no_sale ) )   # rent stops
        self.assertLess( self._operating( self.sold ), self._operating( self.no_sale ) )       # upkeep stops
        self.assertGreater( self._rent_income( self.no_sale ), Decimal( '0' ) )                # (both real streams)

    def test_the_sale_realizes_the_rental_clears_the_mortgage_and_recognizes_the_gain( self ):
        self.assertEqual( self.sold.ledger.market_value( self.sold.chart.account( 'rental' ) ), Decimal( '0' ) )
        self.assertEqual( self.sold.ledger.natural_balance( self.sold.chart.account( 'mortgage' ) ), Decimal( '0' ) )
        self.assertGreater(                                                                    # gain recognized...
            _balance( self.sold, self.sold.chart.income_account( IncomeTaxClass.RENTAL_SALE_GAIN ) ), Decimal( '0' ) )
        self.assertGreater(                                                                    # ...and the rental kept if not sold
            self.no_sale.ledger.market_value( self.no_sale.chart.account( 'rental' ) ), Decimal( '0' ) )
