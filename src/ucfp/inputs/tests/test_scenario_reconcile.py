"""The reconcile views: the one-click "remove stale references" fix every drift surface offers.

`PlansReconcileView` is the core -- it strips a Plans record's references that no longer resolve against
the current Profile; `ScenarioReconcileView` is the thin scenario-keyed wrapper over it. Both are
org-scoped, no-op without a complete profile, and return to the page they were triggered from.
"""
from decimal import Decimal

from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import load_plans, save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.views import PlansReconcileView, ScenarioReconcileView
from ucfp.planning.tests.support import forecast_profile


def _complete_profile( organization ):
    """Persist `forecast_profile` as a *complete* ProfileRecord -- every profile-flow section marked
    reviewed, plus its filing status -- so `completed_profile` returns it."""
    profile = forecast_profile()
    record  = save_profile( organization, profile )
    record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                     if flow_of( section ) == 'profile' and section.form is not None ]
    record.save()
    return record


def _drifted_scenario( organization ):
    """A saved scenario whose Plans hold a repayment for a debt the profile does not have (drift)."""
    plans_record = PlansRecord( organization = organization, label = 'Foo P' )
    save_plans( plans_record, Plans( loan_repayments = [ LoanRepayment(
        debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
        remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )
    assumptions_record = AssumptionsRecord( organization = organization, label = 'Foo A' )
    save_assumptions( assumptions_record, Assumptions() )
    return create_scenario( organization, plans_record, assumptions_record, 'Foo' )


class ScenarioReconcileViewTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()

    def _post( self, uuid, organization = None, referer = None ):
        extra   = { 'HTTP_REFERER': referer } if referer else dict()
        request = self.factory.post( reverse( 'scenario_reconcile', kwargs = { 'uuid': uuid } ), **extra )
        request.organization = organization if organization is not None else self.organization
        return ScenarioReconcileView().post( request, uuid = uuid )

    def _post_plans( self, plans_uuid ):
        request = self.factory.post( reverse( 'plans_reconcile', kwargs = { 'uuid': plans_uuid } ) )
        request.organization = self.organization
        return PlansReconcileView().post( request, uuid = plans_uuid )

    @staticmethod
    def _repayment_debts( scenario ):
        scenario.plans.refresh_from_db()
        return [ r.debt_handle for r in load_plans( scenario.plans ).loan_repayments ]

    def test_scenario_reconcile_strips_drift_via_its_plans( self ):
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        response = self._post( scenario.uuid )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( self._repayment_debts( scenario ), [] )           # the drifted repayment stripped

    def test_the_plans_reconcile_core_strips_drift( self ):
        # The scenario wrapper is thin; the core reconciles a Plans record directly.
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        self._post_plans( scenario.plans.uuid )
        self.assertEqual( self._repayment_debts( scenario ), [] )

    def test_reconcile_returns_to_the_triggering_page( self ):
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        response = self._post( scenario.uuid, referer = 'http://testserver/inputs/scenarios/' )
        self.assertEqual( response.url, 'http://testserver/inputs/scenarios/' )   # back where it came from

    def test_reconcile_falls_back_to_the_scenarios_home_without_a_referer( self ):
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        response = self._post( scenario.uuid )
        self.assertEqual( response.url, reverse( 'scenarios_home' ) )

    def test_reconcile_is_a_no_op_without_a_complete_profile( self ):
        # No complete profile to reconcile against: the plan is left untouched (reconciling against
        # nothing would prune everything), and the view still redirects.
        scenario = _drifted_scenario( self.organization )
        response = self._post( scenario.uuid )
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( self._repayment_debts( scenario ), [ 'gone' ] )   # unchanged

    def test_reconcile_is_scoped_to_the_organization( self ):
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        other    = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._post( scenario.uuid, organization = other )
        self.assertEqual( self._repayment_debts( scenario ), [ 'gone' ] )   # untouched by the foreign post
