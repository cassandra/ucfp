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
from ucfp.parameter_sets.enums import ExpenseCategory, LifestyleLevel, LifestyleScope
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection

from ucfp.inputs.profile.schemas import (
    AssetProfile, CommittedObligation, GovernmentPensionEntitlement, LoanProfile,
    IncomeFlow, PensionEntitlement, Profile, PropertyProfile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    Contribution, DrawdownPolicy, ExpenseFlow, HealthCoverageAssumption, LifestylePlan,
    LifestyleSegment, PlanEvent, RetirementTiming, Plans )
from ucfp.inputs.plans.enums import EventKind
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
        loans = [ LoanProfile( handle = 'mort', name = 'Mortgage',
                               origination_date = date( 2005, 6, 1 ),
                               original_amount = Decimal( '300000' ),
                               interest_rate = Rate( Decimal( '0.0425' ) ),
                               original_term = Duration( 30, TimeUnit.YEAR ),
                               current_balance = Decimal( '250000' ),
                               interest_class = ExpenseTaxClass.MORTGAGE_INTEREST,
                               property_handle = 'home' ) ],
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
        obligations = [ CommittedObligation( handle = 'rent', name = 'Rent',
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
        lifestyle = LifestylePlan(
            scope = LifestyleScope.GENERAL,
            segments = [
                LifestyleSegment( start = date( 2035, 1, 1 ), level = LifestyleLevel.HIGH ),
                LifestyleSegment( start = date( 2050, 1, 1 ), level = LifestyleLevel.MEDIUM ) ] ),
        expenses = [ ExpenseFlow(
            name = 'Property tax', category = ExpenseCategory.HOME,
            expense_tax_class = ExpenseTaxClass.SALT,
            schedule = [ WindowedAmount( Decimal( '6000' ) ) ], property_handle = 'home' ) ],
        contributions = [ Contribution( account_handle = '401k', annual_amount = Decimal( '23000' ),
                                        source = ContributionSource.WAGE ) ],
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
