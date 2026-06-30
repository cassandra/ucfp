"""The Plans <-> Profile compatibility check: every Plans reference must resolve against the Profile."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.parameter_sets.enums import ExpenseCategory
from ucfp.forecast.parameters import WindowedAmount
from ucfp.inputs.profile.schemas import (
    AssetProfile, CommittedObligation, LoanProfile, Profile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    ExpenseFlow, LoanPrepayment, PlanEvent, Plans, RetirementTiming )
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.compatibility import (
    PlansIncompatibleError, assert_compatible, compatibility_issues )


def _profile() -> Profile:
    """A profile with one of each entity kind references resolve against -- subject, account, loan,
    and obligation."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        assets = [ AssetProfile( handle = 'savings', name = 'Savings', asset_class = AssetClass.CASH,
                                 opening_value = Decimal( '1000' ) ) ],
        loans = [ LoanProfile(
            handle = 'mortgage', name = 'Mortgage', origination_date = date( 2010, 1, 1 ),
            original_amount = Decimal( '300000' ), interest_rate = Rate( Decimal( '0.04' ) ),
            original_term = Duration( 30, TimeUnit.YEAR ) ) ],
        obligations = [ CommittedObligation(
            handle = 'rent', name = 'Rent', amount = Decimal( '1500' ),
            cadence = Duration( 1, TimeUnit.MONTH ), expense_tax_class = ExpenseTaxClass.LIVING ) ] )


def _expense( name : str, property_handle ) -> ExpenseFlow:
    return ExpenseFlow(
        name = name, category = ExpenseCategory.HOME, expense_tax_class = ExpenseTaxClass.LIVING,
        schedule = [ WindowedAmount( Decimal( '100' ) ) ], property_handle = property_handle )


class CompatibilityTest( SimpleTestCase ):

    def test_resolving_references_are_compatible( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'you' ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'mortgage',
                                            annual_amount = Decimal( '6000' ) ) ] )
        self.assertEqual( compatibility_issues( _profile(), plans ), [] )
        assert_compatible( _profile(), plans )   # does not raise

    def test_dangling_references_are_reported_and_raise( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'ghost' ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'sold-loan',
                                            annual_amount = Decimal( '6000' ) ) ] )
        issues = compatibility_issues( _profile(), plans )
        self.assertEqual( len( issues ), 2 )
        with self.assertRaises( PlansIncompatibleError ):
            assert_compatible( _profile(), plans )

    def test_optional_property_reference_resolves_or_is_reported( self ):
        # `property_handle` is the only optional reference: None is always fine; a set handle must
        # resolve to a holding.
        compatible = Plans( expenses = [
            _expense( 'General living', None ),     # no property -- the optional branch, always fine
            _expense( 'Upkeep', 'savings' ) ] )     # resolves to a real holding
        self.assertEqual( compatibility_issues( _profile(), compatible ), [] )
        dangling = Plans( expenses = [ _expense( 'Upkeep', 'sold-property' ) ] )
        self.assertEqual( len( compatibility_issues( _profile(), dangling ) ), 1 )

    def test_event_selection_resolves_across_every_entity_type( self ):
        # An event role may point at a subject, account, loan, or obligation -- the only check that
        # resolves against the combined entity set (here a transfer whose target is an obligation).
        compatible = Plans( events = [ PlanEvent(
            kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ), amount = Decimal( '100' ),
            selections = { 'source': 'savings', 'target': 'rent' } ) ] )
        self.assertEqual( compatibility_issues( _profile(), compatible ), [] )
        dangling = Plans( events = [ PlanEvent(
            kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ),
            selections = { 'source': 'nonesuch' } ) ] )
        self.assertEqual( len( compatibility_issues( _profile(), dangling ) ), 1 )
