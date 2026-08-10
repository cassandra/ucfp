"""`delete_property` removes a property and its secured debts from the Profile, but leaves the Plans
untouched -- a repayment plan still keyed to the removed mortgage is *drift*, reconciled on demand at the
run surface rather than eagerly reaped here (the retired reap pattern this bugfix removed)."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile
from ucfp.inputs.properties import delete_property
from ucfp.inputs.plans.schemas import LoanRepayment, Plans


class DeletePropertyTests( SimpleTestCase ):

    def _profile( self ):
        """A property holding with a mortgage secured against it."""
        asset = AssetProfile(
            handle = 'property-1', name = 'Rental', asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = Decimal( '300000' ) )
        mortgage = Debt(
            handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
            balance = Decimal( '200000' ), secured_asset = 'property-1' )
        return Profile( assets = [ asset ], debts = [ mortgage ] )

    def _plans_repaying( self, debt_handle ):
        return Plans( loan_repayments = [ LoanRepayment(
            debt_handle = debt_handle, interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )

    def test_deleting_a_property_removes_its_holding_and_secured_debt( self ):
        profile, _ = delete_property( self._profile(), Plans(), 'property-1' )
        self.assertEqual( profile.assets, [] )
        self.assertEqual( profile.debts, [] )                        # the secured mortgage goes with it

    def test_deleting_a_property_leaves_its_debts_repayment_plan_as_drift( self ):
        # The retired reap: the repayment for the now-gone mortgage is kept, not stripped -- it surfaces
        # as drift at the run surface (a one-click reconcile), never silently reaped on delete.
        plans      = self._plans_repaying( 'debt-1' )
        _, reconciled = delete_property( self._profile(), plans, 'property-1' )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'debt-1' ] )
