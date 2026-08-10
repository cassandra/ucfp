"""`DebtsForm.apply` rebuilds the Profile's debt list from its rows, but leaves the Plans untouched --
a repayment plan still keyed to a debt the user removed here is *drift*, reconciled on demand at the run
surface rather than eagerly reaped on save (the retired reap pattern this bugfix removed)."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.inputs.debts import DebtsForm
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, Profile
from ucfp.inputs.plans.schemas import LoanRepayment, Plans


class DebtsFormReapTests( SimpleTestCase ):

    def _profile( self ):
        return Profile( debts = [ Debt(
            handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE, balance = Decimal( '200000' ) ) ] )

    def _removing_the_debt( self, profile ):
        """A bound, valid form whose one existing debt row is marked for removal."""
        data = { 'handle_0' : 'debt-1', 'secured_0' : '', 'kind_0' : 'MORTGAGE', 'name_0' : 'Mortgage',
                 'balance_0' : '200000', 'remove_0' : 'on',
                 'handle_1' : '', 'secured_1' : '', 'kind_1' : '', 'name_1' : '', 'balance_1' : '' }
        form = DebtsForm( data, profile = profile )
        self.assertTrue( form.is_valid() )
        return form

    def test_removing_a_debt_drops_it_from_the_profile( self ):
        profile   = self._profile()
        result, _ = self._removing_the_debt( profile ).apply( profile, Plans() )
        self.assertEqual( result.debts, [] )

    def test_removing_a_debt_leaves_its_repayment_plan_as_drift( self ):
        # The retired reap: the repayment for the removed debt is kept, not stripped -- it surfaces as
        # drift at the run surface (a one-click reconcile), never silently reaped on save.
        profile = self._profile()
        plans   = Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'debt-1', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )
        _, reconciled = self._removing_the_debt( profile ).apply( profile, plans )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'debt-1' ] )


class VehicleLoanExclusionTests( SimpleTestCase ):
    """Vehicle (auto) loans are owned by the Vehicles section / Vehicle plan: the Debts editor neither
    shows nor offers them, but preserves them across an edit so the rebuild never drops the fact."""

    def _profile( self ):
        return Profile( debts = [
            Debt( handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                  balance = Decimal( '200000' ) ),
            Debt( handle = 'vehicle-1-loan', name = 'Civic loan', kind = DebtKind.AUTO,
                  balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )

    def test_the_editor_shows_only_non_vehicle_debts( self ):
        form  = DebtsForm( profile = self._profile() )
        shown = [ row[ 'name' ].value() for row in form.rows if row[ 'name' ].value() ]
        self.assertEqual( shown, [ 'Mortgage' ] )                  # the vehicle loan is not a row

    def test_auto_is_not_an_addable_kind( self ):
        kinds = { name for name, _label in DebtsForm._KIND_CHOICES }
        self.assertNotIn( DebtKind.AUTO.name, kinds )

    def test_apply_preserves_the_vehicle_loan( self ):
        # Resubmit the mortgage row unchanged (a no-op edit); the un-shown vehicle loan must survive.
        profile = self._profile()
        data    = { 'handle_0' : 'debt-1', 'secured_0' : '', 'kind_0' : 'MORTGAGE', 'name_0' : 'Mortgage',
                    'balance_0' : '200000',
                    'handle_1' : '', 'secured_1' : '', 'kind_1' : '', 'name_1' : '', 'balance_1' : '' }
        form = DebtsForm( data, profile = profile )
        self.assertTrue( form.is_valid() )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( { d.handle for d in result.debts }, { 'debt-1', 'vehicle-1-loan' } )
