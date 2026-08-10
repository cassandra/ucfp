"""`inputs.drift.plans_drift`: the shared drift notice (stale references + one-click reconcile) every
surface renders through the drift pane, keyed by the Plans record that carries the Profile dependencies."""
from decimal import Decimal

from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.drift import plans_drift
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, Profile


class PlansDriftTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _plans_record( self, plans ):
        record = PlansRecord( organization = self.organization, label = 'P' )
        save_plans( record, plans )
        return record

    def test_a_resolving_plan_has_no_drift( self ):
        profile = Profile( debts = [ Debt( handle = 'mortgage', name = 'Mortgage',
                                           kind = DebtKind.MORTGAGE, balance = Decimal( '1000' ) ) ] )
        self.assertIsNone( plans_drift( profile, self._plans_record( Plans() ) ) )

    def test_drift_lists_the_references_and_links_the_reconcile( self ):
        record = self._plans_record( Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )
        notice = plans_drift( Profile(), record )
        self.assertEqual( notice[ 'references' ], [ 'a repayment plan for an unknown debt "gone"' ] )
        self.assertEqual( notice[ 'fix_label' ], 'Remove stale references' )
        self.assertEqual( notice[ 'fix_url' ], f'/inputs/plans/{record.uuid}/reconcile/' )
