"""The Plans <-> Profile compatibility check: every Plans reference must resolve against the Profile."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, LeasedVehicle, Profile, SubjectProfile )
from ucfp.inputs.plans.schemas import (
    CreditCardPlan, LeasedVehicleDisposition, LoanPrepayment, LoanRepayment, PlanEvent, Plans,
    RetirementTiming, VehicleDisposition, VehiclePlan )
from ucfp.inputs.plans.enums import (
    CreditCardPlanMode, EventKind, LeaseDispositionKind, VehicleDispositionKind )
from ucfp.inputs.compatibility import (
    PlansIncompatibleError, assert_compatible, compatibility_issues, plans_without_vehicles )


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


class VehicleDriftTest( SimpleTestCase ):
    """A vehicle-plan disposition (owned or leased) must resolve against the Profile's vehicles, and a
    deleted vehicle's disposition is reaped -- the vehicle counterpart of the debt drift/reap."""

    def _profile( self ):
        return Profile(
            assets = [ AssetProfile( handle = 'vehicle-1', name = 'Car',
                                     asset_class = AssetClass.DEPRECIATING,
                                     opening_value = Decimal( '20000' ) ) ],
            leased_vehicles = [ LeasedVehicle( handle = 'lease-1', name = 'Leased Car' ) ] )

    def _plans( self ):
        return Plans( vehicle_plan = VehiclePlan(
            dispositions = [ VehicleDisposition(
                vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                sale_date = date( 2030, 1, 1 ) ) ],
            leased_dispositions = [ LeasedVehicleDisposition(
                vehicle_handle = 'lease-1', kind = LeaseDispositionKind.RETURN,
                lease_end = date( 2029, 1, 1 ) ) ] ) )

    def test_resolving_vehicle_dispositions_are_compatible( self ):
        self.assertEqual( compatibility_issues( self._profile(), self._plans() ), [] )

    def test_a_disposition_for_a_removed_owned_vehicle_is_flagged( self ):
        issues = compatibility_issues( Profile( leased_vehicles = self._profile().leased_vehicles ),
                                       self._plans() )
        self.assertTrue( any( 'unknown vehicle' in issue for issue in issues ) )

    def test_a_disposition_for_a_removed_leased_vehicle_is_flagged( self ):
        issues = compatibility_issues( Profile( assets = self._profile().assets ), self._plans() )
        self.assertTrue( any( 'unknown leased vehicle' in issue for issue in issues ) )

    def test_reaping_a_vehicle_strips_owned_and_leased_dispositions( self ):
        reaped = plans_without_vehicles( self._plans(), { 'vehicle-1', 'lease-1' } )
        self.assertEqual( reaped.vehicle_plan.dispositions, [] )
        self.assertEqual( reaped.vehicle_plan.leased_dispositions, [] )
