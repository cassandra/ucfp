"""Round-trip tests for the generic dataclass <-> JSON codec.

Exercises every leaf and container type the profile/plans aggregates use, so the codec is
verified independently of either app: Decimal (lossless), date, Enum (by name), the `Rate`
and `Duration` value objects, nested dataclasses, lists, tuples, and Optional/None.
"""
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from django.test import SimpleTestCase

from common.dataclass_json import DataclassJsonError, from_json_data, to_json_data
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.parameters import ContributionSource
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.parameter_sets.enums import (
    CadenceDomain, ExpenseCategory, ExpenseClass, PropertyContext, Realization )
from ucfp.parameter_sets.schemas import ExpenseCatalog, ExpenseType
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection

from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, GovernmentPensionEntitlement,
    IncomeFlow, PensionEntitlement, Profile, PropertyProfile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    Vehicle, VehiclePlan, VehicleRunningCost, Contribution, CreditCardPlan, DrawdownPolicy,
    HealthCoverageAssumption, IncomeTiming, LoanRepayment, PlanEvent, PropertyExpense, RecurringExpense,
    RetirementTiming, RothConversion, Withdrawal, Plans )
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind
from ucfp.inputs.assumptions.schemas import Assumptions


@dataclass( frozen = True )
class _FieldNamedAsType:
    """A field named the same as its type, with a default -- the footgun the codec must reject (the
    `date = None` default binds a class attribute that shadows the `date` type when hints are resolved)."""
    date: Optional[ date ] = None


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
            IncomeFlow( handle = 'income-0', name = 'Salary', subject_handle = 'you',
                        income_tax_class = IncomeTaxClass.WAGES, amount = Decimal( '120000' ) ),
            IncomeFlow( handle = 'home', name = 'Home rent', subject_handle = 'you',
                        income_tax_class = IncomeTaxClass.GROSS_RENTAL, amount = Decimal( '2500' ),
                        interval = Duration( 1, TimeUnit.MONTH ), property_handle = 'home' ) ],
        pensions = [ PensionEntitlement( subject_handle = 'you',
                                         base_annual_amount = Decimal( '30000' ),
                                         normal_start_age = 65 ) ],
        government_pension = [ GovernmentPensionEntitlement(
            subject_handle = 'you', monthly_at_normal_age = Decimal( '2800.50' ) ) ],
    )


def _sample_assumptions():
    return Assumptions(
        economics = EconomicParameters(
            inflation = Rate( Decimal( '0.03' ) ), medical_inflation = Rate( Decimal( '0.045' ) ),
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
        income_timing = [ IncomeTiming( flow_handle = 'income-0', end = date( 2035, 1, 1 ) ),
                          IncomeTiming( flow_handle = 'home' ) ],
        expense_spans = [ 70, 80, None ],
        recurring_expenses = [ RecurringExpense(
            name = 'Travel', handle = 'travel', category = ExpenseCategory.DISCRETIONARY,
            expense_tax_class = ExpenseTaxClass.LIVING, interval = Duration( 1, TimeUnit.YEAR ),
            amounts = [ Decimal( '900' ), Decimal( '500' ), Decimal( '200' ) ] ) ],
        property_expenses = [ PropertyExpense(
            name = 'Property tax', handle = 'property-tax', category = ExpenseCategory.TAXES_INSURANCE,
            expense_tax_class = ExpenseTaxClass.SALT, interval = Duration( 1, TimeUnit.MONTH ),
            applies_to = ( PropertyContext.RESIDENCE, PropertyContext.RENTAL ),
            default_amount = Decimal( '6000' ),
            overrides = { 'home': Decimal( '6500' ) } ),
            PropertyExpense(
                name = 'Appliance', handle = 'appliance', category = ExpenseCategory.MAINTENANCE_REPAIR,
                expense_tax_class = ExpenseTaxClass.LIVING,
                applies_to = ( PropertyContext.RESIDENCE, ), interval = Duration( 1, TimeUnit.YEAR ),
                default_amount = Decimal( '580' ), count = 3, cost_each = Decimal( '2900' ),
                lifespan = 15 ) ],
        contributions = [ Contribution(
            handle = 'contribution-1', account_handle = '401k', amount = Decimal( '1900' ),
            source = ContributionSource.WAGE, interval = Duration( 1, TimeUnit.MONTH ),
            start_age = 50, end_age = 65 ) ],
        roth_conversions = [ RothConversion(
            handle = 'conversion-1', source_handle = 'pretax-subject', amount = Decimal( '30000' ),
            interval = Duration( 1, TimeUnit.YEAR ), start_age = 63, end_age = 70 ) ],
        withdrawals = [ Withdrawal(
            handle = 'withdrawal-1', source_handle = 'pretax-subject', amount = Decimal( '20000' ),
            start_age = 72 ) ],
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
        vehicle_plan = VehiclePlan(
            vehicles = [
                Vehicle( handle = 'vehicle-1', name = 'Sedan', purchase_date = date( 2031, 1, 1 ),
                         purchase_price = Decimal( '35000' ), recurrence_years = 8,
                         down_payment = Decimal( '7000' ) ),
                Vehicle( handle = 'vehicle-2', name = 'Pickup', purchase_date = date( 2033, 6, 1 ),
                         end_date = date( 2045, 1, 1 ), purchase_price = Decimal( '48000' ),
                         recurrence_years = 10, monthly_payment = Decimal( '600' ) ) ],
            running_costs = [
                VehicleRunningCost(
                    name = 'Fuel', handle = 'gasoline', expense_tax_class = ExpenseTaxClass.LIVING,
                    interval = Duration( 1, TimeUnit.WEEK ), amount = Decimal( '20' ) ),
                VehicleRunningCost(
                    name = 'Insurance', handle = 'auto-insurance',
                    expense_tax_class = ExpenseTaxClass.LIVING,
                    interval = Duration( 6, TimeUnit.MONTH ), amount = Decimal( '750' ),
                    realization = Realization.DISCRETE, cadence_domain = CadenceDomain.MO_YR ) ] ),
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
                name = 'Property Tax', handle = 'property-tax', expense_class = ExpenseClass.PROPERTY,
                category = ExpenseCategory.TAXES_INSURANCE, order = 10,
                expense_tax_class = ExpenseTaxClass.SALT, default_amount = Decimal( '6000' ),
                interval = Duration( 1, TimeUnit.YEAR ), realization = Realization.DISCRETE,
                cadence_domain = CadenceDomain.MO_YR,
                applies_to = ( PropertyContext.RESIDENCE, PropertyContext.RENTAL ) ),
            ExpenseType(
                name = 'Umbrella Insurance', handle = 'umbrella-insurance', expense_class = ExpenseClass.LIVING,
                category = ExpenseCategory.MISCELLANEOUS, order = 10,
                expense_tax_class = ExpenseTaxClass.LIVING, default_amount = Decimal( '500' ),
                interval = Duration( 1, TimeUnit.YEAR ), realization = Realization.DISCRETE,
                cadence_domain = CadenceDomain.MO_YR ) ] )
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
            from_json_data( ExpenseCategory, 'GIVING' )   # a category the model no longer defines
        message = str( caught.exception )
        self.assertIn( 'GIVING', message )
        self.assertIn( 'ExpenseCategory', message )
        self.assertIn( 'schema change', message )

    def test_a_field_named_as_its_type_is_rejected_loudly( self ):
        # The field-named-as-its-type footgun: a `date: Optional[date] = None` field shadows the type, so
        # its annotation resolves to NoneType and the value would silently fail to deserialize (an ISO
        # string staying a string). The codec catches it by name rather than round-tripping corrupt data.
        with self.assertRaises( DataclassJsonError ) as caught:
            from_json_data( _FieldNamedAsType, { 'date': '2032-06-01' } )
        message = str( caught.exception )
        self.assertIn( '_FieldNamedAsType', message )
        self.assertIn( 'NoneType', message )


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

    def test_typed_dict_values_coerce_to_their_declared_type( self ):
        # A `dict[str, Decimal]` (e.g. PropertyExpense.overrides) must bring its VALUES back as Decimal,
        # not leave them as the strings serialization produced -- the codec deserializes each value by
        # the declared value type rather than copying the dict verbatim.
        restored = from_json_data( dict[ str, Decimal ], { 'home': '6500', 'rental': '9000.50' } )
        self.assertEqual( restored, { 'home': Decimal( '6500' ), 'rental': Decimal( '9000.50' ) } )
        self.assertIsInstance( restored[ 'home' ], Decimal )

    def test_untyped_dict_passes_values_through( self ):
        # A bare `dict` (no type args) has no value type to coerce to, so values pass through unchanged.
        self.assertEqual( from_json_data( dict, { 'a': 1, 'b': 'x' } ), { 'a': 1, 'b': 'x' } )

    def test_unsupported_type_raises( self ):
        with self.assertRaises( TypeError ):
            to_json_data( object() )
