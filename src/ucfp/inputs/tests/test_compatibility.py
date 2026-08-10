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
    Contribution, CreditCardPlan, DrawdownPolicy, LeasedVehicleDisposition, LoanPrepayment, LoanRepayment,
    PlanEvent, Plans, RetirementTiming, RothConversion, VehicleDisposition, VehiclePlan, Withdrawal )
from ucfp.inputs.plans.enums import (
    CreditCardPlanMode, EventKind, LeaseDispositionKind, VehicleDispositionKind )
from ucfp.forecast.parameters import ContributionSource
from ucfp.inputs.compatibility import (
    PlansIncompatibleError, assert_compatible, compatibility_issues, plans_reconciled_with_profile,
    plans_without_vehicles )


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
        # Reaping every current vehicle empties both disposition lists, and an emptied plan collapses to
        # None (as every form apply does), leaving no spurious plan behind.
        self.assertIsNone(
            plans_without_vehicles( self._plans(), { 'vehicle-1', 'lease-1' } ).vehicle_plan )
        # Reaping just the owned vehicle strips its disposition and leaves the leased one intact.
        kept = plans_without_vehicles( self._plans(), { 'vehicle-1' } ).vehicle_plan
        self.assertEqual( kept.dispositions, [] )
        self.assertEqual( [ d.vehicle_handle for d in kept.leased_dispositions ], [ 'lease-1' ] )


def _full_profile() -> Profile:
    """A profile with one of every entity a Plans reference can name: a subject, two accounts (one a
    depreciating vehicle), a debt, and a leased vehicle."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        assets = [ AssetProfile( handle = 'savings', name = 'Savings', asset_class = AssetClass.CASH,
                                 opening_value = Decimal( '1000' ) ),
                   AssetProfile( handle = 'vehicle-1', name = 'Car', asset_class = AssetClass.DEPRECIATING,
                                 opening_value = Decimal( '20000' ) ) ],
        debts = [ Debt( handle = 'mortgage', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                        balance = Decimal( '300000' ) ) ],
        leased_vehicles = [ LeasedVehicle( handle = 'lease-1', name = 'Leased Car' ) ] )


class ReconcileTests( SimpleTestCase ):
    """`plans_reconciled_with_profile` -- the write-side twin of `compatibility_issues`: it prunes every
    reference that does not resolve, keeping the ones that do, so the result is compatible."""

    _MONTHLY = Duration( 1, TimeUnit.MONTH )

    def _mixed_plans( self ) -> Plans:
        """A plan carrying, in every category, one reference that resolves against `_full_profile` and one
        that does not (a removed handle) -- so reconcile must keep the first and drop the second."""
        return Plans(
            timing = [ RetirementTiming( subject_handle = 'you' ),
                       RetirementTiming( subject_handle = 'ghost' ) ],
            contributions = [
                Contribution( handle = 'c1', account_handle = 'savings', amount = Decimal( '100' ),
                              source = ContributionSource.PERSONAL, interval = self._MONTHLY ),
                Contribution( handle = 'c2', account_handle = 'gone', amount = Decimal( '100' ),
                              source = ContributionSource.PERSONAL, interval = self._MONTHLY ) ],
            roth_conversions = [
                RothConversion( handle = 'r1', source_handle = 'savings', amount = Decimal( '1000' ) ),
                RothConversion( handle = 'r2', source_handle = 'gone', amount = Decimal( '1000' ) ) ],
            withdrawals = [
                Withdrawal( handle = 'w1', source_handle = 'savings', amount = Decimal( '500' ) ),
                Withdrawal( handle = 'w2', source_handle = 'gone', amount = Decimal( '500' ) ) ],
            loan_repayments = [
                LoanRepayment( debt_handle = 'mortgage', interest_rate = Rate( Decimal( '0.04' ) ),
                               remaining_term = Duration( 25, TimeUnit.YEAR ) ),
                LoanRepayment( debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
                               remaining_term = Duration( 25, TimeUnit.YEAR ) ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'mortgage', annual_amount = Decimal( '6000' ) ),
                            LoanPrepayment( loan_handle = 'gone', annual_amount = Decimal( '6000' ) ) ],
            credit_card_plans = [
                CreditCardPlan( card_handle = 'mortgage', mode = CreditCardPlanMode.MONTHLY,
                                monthly_payment = Decimal( '200' ) ),
                CreditCardPlan( card_handle = 'gone', mode = CreditCardPlanMode.MONTHLY,
                                monthly_payment = Decimal( '200' ) ) ],
            vehicle_plan = VehiclePlan(
                dispositions = [
                    VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                                        sale_date = date( 2030, 1, 1 ) ),
                    VehicleDisposition( vehicle_handle = 'gone', kind = VehicleDispositionKind.SELL,
                                        sale_date = date( 2030, 1, 1 ) ) ],
                leased_dispositions = [
                    LeasedVehicleDisposition( vehicle_handle = 'lease-1',
                                              kind = LeaseDispositionKind.RETURN,
                                              lease_end = date( 2029, 1, 1 ) ),
                    LeasedVehicleDisposition( vehicle_handle = 'gone',
                                              kind = LeaseDispositionKind.RETURN,
                                              lease_end = date( 2029, 1, 1 ) ) ] ),
            drawdown = DrawdownPolicy( sweep_allocation = [ ( 'savings', Decimal( '0.6' ) ),
                                                            ( 'gone', Decimal( '0.4' ) ) ] ),
            events = [
                PlanEvent( kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ), amount = Decimal( '100' ),
                           selections = { 'source': 'savings', 'target': 'mortgage' } ),
                PlanEvent( kind = EventKind.TRANSFER, date = date( 2030, 1, 1 ), amount = Decimal( '100' ),
                           selections = { 'source': 'savings', 'target': 'gone' } ) ] )

    def test_reconcile_makes_a_drifted_plan_compatible( self ):
        # The invariant: reconciling a plan that drifts in every category leaves it fully compatible.
        profile, plans = _full_profile(), self._mixed_plans()
        self.assertTrue( compatibility_issues( profile, plans ) )                  # drifted to begin with
        reconciled = plans_reconciled_with_profile( profile, plans )
        self.assertEqual( compatibility_issues( profile, reconciled ), [] )

    def test_reconcile_keeps_every_resolving_reference( self ):
        # Only the removed handle is dropped in each category; the resolving one survives.
        reconciled = plans_reconciled_with_profile( _full_profile(), self._mixed_plans() )
        self.assertEqual( [ t.subject_handle for t in reconciled.timing ], [ 'you' ] )
        self.assertEqual( [ c.account_handle for c in reconciled.contributions ], [ 'savings' ] )
        self.assertEqual( [ v.source_handle for v in reconciled.roth_conversions ], [ 'savings' ] )
        self.assertEqual( [ w.source_handle for w in reconciled.withdrawals ], [ 'savings' ] )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'mortgage' ] )
        self.assertEqual( [ p.loan_handle for p in reconciled.prepayments ], [ 'mortgage' ] )
        self.assertEqual( [ c.card_handle for c in reconciled.credit_card_plans ], [ 'mortgage' ] )
        self.assertEqual(
            [ d.vehicle_handle for d in reconciled.vehicle_plan.dispositions ], [ 'vehicle-1' ] )
        self.assertEqual(
            [ d.vehicle_handle for d in reconciled.vehicle_plan.leased_dispositions ], [ 'lease-1' ] )
        self.assertEqual( [ handle for handle, _ in reconciled.drawdown.sweep_allocation ], [ 'savings' ] )
        self.assertEqual( len( reconciled.events ), 1 )         # the all-resolving event kept

    def test_reconcile_collapses_an_emptied_vehicle_plan( self ):
        # A vehicle plan whose only disposition is for a removed vehicle collapses to None (not a spurious
        # empty plan), matching every form apply.
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'gone', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2030, 1, 1 ) ) ] ) )
        self.assertIsNone( plans_reconciled_with_profile( _full_profile(), plans ).vehicle_plan )

    def test_reconcile_renormalizes_a_pruned_cash_sweep( self ):
        # Dropping a sweep weight on a removed account rescales the survivors so the weights still sum to
        # 1 -- else the allocation would be invalid (AssetAllocation requires a sum of 1).
        plans = Plans( drawdown = DrawdownPolicy( sweep_allocation = [
            ( 'savings', Decimal( '0.6' ) ), ( 'vehicle-1', Decimal( '0.1' ) ),
            ( 'gone', Decimal( '0.3' ) ) ] ) )
        swept = plans_reconciled_with_profile( _full_profile(), plans ).drawdown.sweep_allocation
        self.assertEqual( [ handle for handle, _ in swept ], [ 'savings', 'vehicle-1' ] )
        self.assertEqual( sum( ( weight for _, weight in swept ), Decimal( '0' ) ), Decimal( '1' ) )

    def test_reconcile_clears_a_fully_dangling_cash_sweep( self ):
        # When every swept account is gone, the sweep empties (the engine then simply does not sweep).
        plans = Plans( drawdown = DrawdownPolicy( sweep_allocation = [ ( 'gone', Decimal( '1' ) ) ] ) )
        self.assertEqual(
            plans_reconciled_with_profile( _full_profile(), plans ).drawdown.sweep_allocation, [] )

    def test_reconcile_leaves_a_clean_plan_unchanged( self ):
        # A plan with no drift reconciles to an equal plan (nothing pruned).
        clean = Plans( timing = [ RetirementTiming( subject_handle = 'you' ) ],
                       loan_repayments = [ LoanRepayment(
                           debt_handle = 'mortgage', interest_rate = Rate( Decimal( '0.04' ) ),
                           remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )
        self.assertEqual( plans_reconciled_with_profile( _full_profile(), clean ), clean )
