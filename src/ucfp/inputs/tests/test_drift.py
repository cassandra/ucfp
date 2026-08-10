"""`inputs.drift.scenario_drift`: the shared drift notice (stale references + one-click reconcile) that
every surface renders through the `scenario_drift` pane."""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.drift import scenario_drift
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, Profile


class ScenarioDriftTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _scenario( self, plans ):
        record = PlansRecord( organization = self.organization, label = 'P' )
        save_plans( record, plans )
        return SimpleNamespace( plans = record, uuid = uuid4() )

    def test_a_resolving_plan_has_no_drift( self ):
        profile  = Profile( debts = [ Debt( handle = 'mortgage', name = 'Mortgage',
                                            kind = DebtKind.MORTGAGE, balance = Decimal( '1000' ) ) ] )
        scenario = self._scenario( Plans() )
        self.assertIsNone( scenario_drift( profile, scenario ) )

    def test_drift_lists_the_references_and_links_the_reconcile( self ):
        scenario = self._scenario( Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )
        notice = scenario_drift( Profile(), scenario )
        self.assertEqual( notice[ 'references' ], [ 'a repayment plan for an unknown debt "gone"' ] )
        self.assertEqual( notice[ 'fix_label' ], 'Remove stale references' )
        self.assertEqual( notice[ 'fix_url' ], f'/inputs/scenarios/{scenario.uuid}/reconcile/' )
