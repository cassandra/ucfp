"""Round-trip tests for the generic dataclass <-> JSON codec.

Exercises every leaf and container type the profile/plans aggregates use, so the codec is
verified independently of either app: Decimal (lossless), date, Enum (by name), the `Rate`
and `Duration` value objects, nested dataclasses, lists, tuples, and Optional/None.
"""
import json
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.date_window import DateWindow
from common.dataclass_json import DataclassJsonError, from_json_data, to_json_data
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.parameters import ContributionSource, WindowedAmount
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext
from ucfp.parameter_sets.schemas import ExpenseCatalog, ExpenseType
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection

from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    AssetProfile, CommittedObligation, Debt, GovernmentPensionEntitlement,
    IncomeFlow, PensionEntitlement, Profile, PropertyProfile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    AutoPlan, Contribution, CreditCardPlan, DrawdownPolicy, HealthCoverageAssumption,
    LoanRepayment, PlanEvent, PropertyExpense, RecurringExpense, RetirementTiming, Plans )
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind
from ucfp.inputs.assumptions.schemas import Assumptions


def _sample_profile():
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1970, 5, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'brok', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '100000.00' ), cost_basis = Decimal( '60000' ),
                          owner_handle = 'you' ),
            AssetProfile( handle = 'home', name = 'Home',
                          asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
                          opening_value = Decimal( '500000' ), cost_basis = Decimal( '300000' ),
                          property = PropertyProfile( acquisition_date = date( 2005, 6, 1 ),
                                                      depreciable_basis = Decimal( '0' ),
                                                      property_type = RealPropertyType.RESIDENTIAL ) ),
        ],
        debts = [ Debt( handle = 'mort', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                        balance = Decimal( '250000' ), secured_asset = 'home' ) ],
        income_flows = [
            IncomeFlow( name = 'Salary', subject_handle = 'you',
                        income_tax_class = IncomeTaxClass.WAGES,
                        schedule = [ WindowedAmount( Decimal( '120000' ),
                                                     DateWindow( end = date( 2035, 1, 1 ) ) ) ] ),
            IncomeFlow( name = 'Home rent', subject_handle = 'you',
                        income_tax_class = IncomeTaxClass.GROSS_RENTAL,
                        schedule = [ WindowedAmount( Decimal( '2500' ) ) ],
                        interval = Duration( 1, TimeUnit.MONTH ), property_handle = 'home' ) ],
        pensions = [ PensionEntitlement( subject_handle = 'you',
                                         base_annual_amount = Decimal( '30000' ),
                                         normal_start_age = 65 ) ],
        government_pension = [ GovernmentPensionEntitlement(
            subject_handle = 'you', monthly_at_normal_age = Decimal( '2800.50' ) ) ],
        obligations = [ CommittedObligation( handle = 'tuition', name = 'Tuition',
                                             amount = Decimal( '1500' ),
                                             cadence = Duration( 1, TimeUnit.MONTH ),
                                             expense_tax_class = ExpenseTaxClass.LIVING ) ],
    )


def _sample_assumptions():
    return Assumptions(
        economics = EconomicParameters(
            inflation = Rate( Decimal( '0.025' ) ), medical_inflation = Rate( Decimal( '0.045' ) ),
            wage_growth = Rate( Decimal( '0.03' ) ), savings_interest = Rate( Decimal( '0.02' ) ),
            cd_interest = Rate( Decimal( '0.03' ) ), bond_interest = Rate( Decimal( '0.04' ) ),
            stock_appreciation = Rate( Decimal( '0.06' ) ), stock_dividend = Rate( Decimal( '0.018' ) ),
            real_estate_appreciation = Rate( Decimal( '0.035' ) ),
            retirement_growth = Rate( Decimal( '0.055' ) ),
            social_security_cola = Rate( Decimal( '0.025' ) ), pension_cola = Rate( Decimal( '0.02' ) ),
            rental_increase = Rate( Decimal( '0.03' ) ) ),
        tax_projection = TaxProjection(
            forecast_type = StatuteForecastType.CURRENT_LAW ) )


def _sample_plans():
    return Plans(
        timing = [ RetirementTiming(
            subject_handle = 'you',
            government_pension_claiming_date = date( 2040, 1, 1 ),
            pension_start = date( 2038, 1, 1 ) ) ],
        expense_spans = [ 70, 80, None ],
        recurring_expenses = [ RecurringExpense(
            name = 'Travel', category = ExpenseCategory.DISCRETIONARY,
            expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = [ Decimal( '900' ), Decimal( '500' ), Decimal( '200' ) ] ) ],
        property_expenses = [ PropertyExpense(
            name = 'Property tax', category = ExpenseCategory.PROPERTY,
            expense_tax_class = ExpenseTaxClass.SALT,
            applies_to = ( PropertyContext.RESIDENCE, PropertyContext.RENTAL ),
            default_amount = Decimal( '6000' ),
            overrides = { 'home': Decimal( '6500' ) } ) ],
        contributions = [ Contribution( account_handle = '401k', annual_amount = Decimal( '23000' ),
                                        source = ContributionSource.WAGE ) ],
        loan_repayments = [ LoanRepayment( debt_handle = 'mort',
                                           interest_rate = Rate( Decimal( '0.0425' ) ),
                                           remaining_term = Duration( 25, TimeUnit.YEAR ) ) ],
        credit_card_plans = [
            CreditCardPlan( card_handle = 'visa', mode = CreditCardPlanMode.MONTHLY,
                            monthly_payment = Decimal( '250' ) ),
            CreditCardPlan( card_handle = 'amex', mode = CreditCardPlanMode.LUMP,
                            target_date = date( 2029, 3, 1 ) ),
            CreditCardPlan( card_handle = 'disc', mode = CreditCardPlanMode.COMBO,
                            monthly_payment = Decimal( '150' ), target_date = date( 2030, 1, 1 ) ) ],
        auto_plan = AutoPlan(
            num_cars = 2, purchase_price = Decimal( '35000' ), recurrence_years = 8,
            start_date = date( 2031, 1, 1 ), down_payment = Decimal( '7000' ) ),
        drawdown = DrawdownPolicy( cash_floor = Decimal( '20000' ), cash_ceiling = Decimal( '50000' ),
                                   draw_order = [ AssetClass.STOCKS, AssetClass.BONDS ],
                                   sweep_allocation = [ ( 'brok', Decimal( '0.6' ) ),
                                                        ( 'bond', Decimal( '0.4' ) ) ] ),
        events = [
            PlanEvent( kind = EventKind.TRANSFER, date = date( 2040, 1, 1 ),
                       amount = Decimal( '15000' ),
                       selections = { 'source': 'brok', 'target': 'savings' } ),
            PlanEvent( kind = EventKind.DEATH, date = date( 2060, 1, 1 ),
                       selections = { 'subject': 'spouse' } ) ],
        health_coverage = HealthCoverageAssumption( household_size = 2,
                                                    reference_premium = Decimal( '12000' ),
                                                    start = date( 2035, 1, 1 ) ),
    )


class DataclassJsonRoundTripTest( SimpleTestCase ):

    def test_profile_round_trips( self ):
        profile = _sample_profile()
        data = to_json_data( profile )
        json.dumps( data )  # must be JSON-serializable
        self.assertEqual( from_json_data( Profile, data ), profile )

    def test_plans_round_trips( self ):
        plans = _sample_plans()
        data = to_json_data( plans )
        json.dumps( data )
        self.assertEqual( from_json_data( Plans, data ), plans )

    def test_assumptions_round_trips( self ):
        assumptions = _sample_assumptions()
        data = to_json_data( assumptions )
        json.dumps( data )
        self.assertEqual( from_json_data( Assumptions, data ), assumptions )

    def test_expense_catalog_applies_to_round_trips( self ):
        # The catalog's tuple-of-enum `applies_to` is the codec branch this rework relies on: a
        # non-empty tuple serializes to a JSON list of names and rebuilds as a tuple, and an empty
        # tuple (a household row) survives as ().
        catalog = ExpenseCatalog( expenses = [
            ExpenseType(
                name = 'Property Tax', category = ExpenseCategory.PROPERTY,
                expense_tax_class = ExpenseTaxClass.SALT, default_amount = Decimal( '6000' ),
                interval = Duration( 1, TimeUnit.YEAR ),
                applies_to = ( PropertyContext.RESIDENCE, PropertyContext.RENTAL ) ),
            ExpenseType(
                name = 'Umbrella Insurance', category = ExpenseCategory.MISCELLANEOUS,
                expense_tax_class = ExpenseTaxClass.LIVING, default_amount = Decimal( '500' ) ) ] )
        data = to_json_data( catalog )
        json.dumps( data )
        self.assertEqual( data[ 'expenses' ][ 0 ][ 'applies_to' ], [ 'RESIDENCE', 'RENTAL' ] )
        self.assertEqual( data[ 'expenses' ][ 1 ][ 'applies_to' ], [] )
        restored = from_json_data( ExpenseCatalog, data )
        self.assertEqual( restored, catalog )
        self.assertEqual(
            restored.expenses[ 0 ].applies_to,
            ( PropertyContext.RESIDENCE, PropertyContext.RENTAL ) )

    def test_empty_aggregates_round_trip( self ):
        self.assertEqual( from_json_data( Profile, to_json_data( Profile() ) ), Profile() )
        self.assertEqual( from_json_data( Plans, to_json_data( Plans() ) ), Plans() )
        self.assertEqual(
            from_json_data( Assumptions, to_json_data( Assumptions() ) ), Assumptions() )

    def test_incompatible_stored_record_reports_clearly( self ):
        # A record missing a now-required field (an older schema) names the type and the field gap,
        # not a raw TypeError from deep in construction.
        stale = { 'handle': 'you', 'name': 'You' }   # missing the required birthdate
        with self.assertRaises( DataclassJsonError ) as caught:
            from_json_data( SubjectProfile, stale )
        message = str( caught.exception )
        self.assertIn( 'SubjectProfile', message )
        self.assertIn( 'schema change', message )

    def test_removed_enum_member_reports_clearly( self ):
        # A stored enum value that no longer exists (a member removed or renamed since it was saved)
        # names the enum and the missing value, not a raw KeyError from deep in construction.
        with self.assertRaises( DataclassJsonError ) as caught:
            from_json_data( ExpenseCategory, 'UTILITIES' )   # a category the model no longer defines
        message = str( caught.exception )
        self.assertIn( 'UTILITIES', message )
        self.assertIn( 'ExpenseCategory', message )
        self.assertIn( 'schema change', message )


class DataclassJsonLeafTest( SimpleTestCase ):

    def test_decimal_is_lossless( self ):
        value = Decimal( '12345.6789012345' )
        self.assertEqual( from_json_data( Decimal, to_json_data( value ) ), value )

    def test_enum_serializes_by_member_name( self ):
        self.assertEqual( to_json_data( AssetClass.STOCKS ), 'STOCKS' )
        self.assertIs( from_json_data( AssetClass, 'STOCKS' ), AssetClass.STOCKS )

    def test_value_objects_round_trip( self ):
        rate = Rate( Decimal( '0.0375' ) )
        duration = Duration( 3, TimeUnit.MONTH )
        self.assertEqual( from_json_data( Rate, to_json_data( rate ) ), rate )
        self.assertEqual( from_json_data( Duration, to_json_data( duration ) ), duration )

    def test_unsupported_type_raises( self ):
        with self.assertRaises( TypeError ):
            to_json_data( object() )
