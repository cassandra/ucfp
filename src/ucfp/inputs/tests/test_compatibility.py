"""The Plans <-> Profile compatibility check: every Plans reference must resolve against the Profile."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, Profile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    CreditCardPlan, LoanPrepayment, LoanRepayment, PlanEvent, Plans, RetirementTiming )
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind
from ucfp.inputs.compatibility import (
    PlansIncompatibleError, assert_compatible, compatibility_issues )


def _profile() -> Profile:
    """A profile with one of each entity kind references resolve against -- subject, account, and
    debt."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        assets = [ AssetProfile( handle = 'savings', name = 'Savings', asset_class = AssetClass.CASH,
                                 opening_value = Decimal( '1000' ) ) ],
        debts = [ Debt( handle = 'mortgage', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                        balance = Decimal( '300000' ) ) ] )


class CompatibilityTest( SimpleTestCase ):

    def test_resolving_references_are_compatible( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'you' ) ],
            loan_repayments = [ LoanRepayment(
                debt_handle = 'mortgage', interest_rate = Rate( Decimal( '0.04' ) ),
                remaining_term = Duration( 25, TimeUnit.YEAR ) ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'mortgage',
                                            annual_amount = Decimal( '6000' ) ) ] )
        self.assertEqual( compatibility_issues( _profile(), plans ), [] )
        assert_compatible( _profile(), plans )   # does not raise

    def test_dangling_references_are_reported_and_raise( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'ghost' ) ],
            loan_repayments = [ LoanRepayment(
                debt_handle = 'sold-debt', interest_rate = Rate( Decimal( '0.04' ) ),
                remaining_term = Duration( 25, TimeUnit.YEAR ) ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'sold-loan',
                                            annual_amount = Decimal( '6000' ) ) ],
            credit_card_plans = [ CreditCardPlan(
                card_handle = 'sold-card', mode = CreditCardPlanMode.MONTHLY,
                monthly_payment = Decimal( '200' ) ) ] )
        issues = compatibility_issues( _profile(), plans )
        self.assertEqual( len( issues ), 4 )
        with self.assertRaises( PlansIncompatibleError ):
            assert_compatible( _profile(), plans )

    def test_event_selection_resolves_across_every_entity_type( self ):
        # An event role may point at a subject, account, or debt -- the only check that resolves
        # against the combined entity set (here a transfer whose target is a debt).
        compatible = Plans( events = [ PlanEvent(
            kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ), amount = Decimal( '100' ),
            selections = { 'source': 'savings', 'target': 'mortgage' } ) ] )
        self.assertEqual( compatibility_issues( _profile(), compatible ), [] )
        dangling = Plans( events = [ PlanEvent(
            kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ),
            selections = { 'source': 'nonesuch' } ) ] )
        self.assertEqual( len( compatibility_issues( _profile(), dangling ) ), 1 )
