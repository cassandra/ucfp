"""The reconcile views: the one-click "remove stale references" fix every drift surface offers.

`PlansReconcileView` is the core -- it strips a Plans record's references that no longer resolve against
the current Profile; `ScenarioReconcileView` is the thin scenario-keyed wrapper over it. Both are
org-scoped, no-op without a complete profile, and return to the page they were triggered from.
"""
from dataclasses import replace
from decimal import Decimal

from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.compatibility import home_rent_drift, loan_terms_drift
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import load_plans, save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, LoanTermsSnapshot, Plans
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.profile.schemas import Debt, LoanTerms
from ucfp.inputs.property_expenses import (
    RENT_EXPENSE_HANDLE, merged_property_expenses, set_home_rent )
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.views import (
    PlansHomeRentKeepView, PlansHomeRentResetView, PlansLoanTermsKeepView, PlansLoanTermsResetView,
    PlansReconcileView, ScenarioReconcileView )
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
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


def _drifted_plans_record( organization, label = 'Foo P' ):
    """A Plans record holding a repayment for a debt the profile does not have (drift)."""
    plans_record = PlansRecord( organization = organization, label = label )
    save_plans( plans_record, Plans( loan_repayments = [ LoanRepayment(
        debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
        remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )
    return plans_record


def _scenario_on( organization, plans_record, label ):
    """A saved scenario built on `plans_record` (its own fresh assumptions)."""
    assumptions_record = AssumptionsRecord( organization = organization, label = f'{label} A' )
    save_assumptions( assumptions_record, Assumptions() )
    return create_scenario( organization, plans_record, assumptions_record, label )


def _drifted_scenario( organization ):
    """A saved scenario whose Plans hold a repayment for a debt the profile does not have (drift)."""
    return _scenario_on( organization, _drifted_plans_record( organization ), 'Foo' )


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

    def test_reconciling_shared_plans_clears_drift_for_every_scenario_on_them( self ):
        # Plans, not scenarios, carry the Profile dependencies: a Plans record shared across scenarios
        # holds one set of references, so a single Plans-keyed reconcile clears the drift for all of them.
        _complete_profile( self.organization )
        shared    = _drifted_plans_record( self.organization )
        first     = _scenario_on( self.organization, shared, 'First' )
        second    = _scenario_on( self.organization, shared, 'Second' )
        self._post_plans( shared.uuid )
        self.assertEqual( self._repayment_debts( first  ), [] )
        self.assertEqual( self._repayment_debts( second ), [] )

    def test_reconcile_is_scoped_to_the_organization( self ):
        _complete_profile( self.organization )
        scenario = _drifted_scenario( self.organization )
        other    = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._post( scenario.uuid, organization = other )
        self.assertEqual( self._repayment_debts( scenario ), [ 'gone' ] )   # untouched by the foreign post


def _profile_with_termed_debt( organization, rate ):
    """A complete profile whose one amortizing debt carries contract terms at `rate`."""
    profile = replace( forecast_profile(), debts = [ Debt(
        handle = 'debt-1', name = 'Student loan', kind = DebtKind.STUDENT, balance = Decimal( '15000' ),
        terms = LoanTerms( interest_rate = Rate.percent( rate ),
                           remaining_term = Duration( 48, TimeUnit.MONTH ) ) ) ] )
    record = save_profile( organization, profile )
    record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                     if flow_of( section ) == 'profile' and section.form is not None ]
    record.save()
    return record


def _loan_terms_drifted_plans_record( organization ):
    """A Plans record whose repayment (5%) seeded from a contract (snapshot 6%) the profile has since
    changed -- so it drifts against a 7% profile."""
    record = PlansRecord( organization = organization, label = 'LT P' )
    save_plans( record, Plans(
        loan_repayments      = [ LoanRepayment( 'debt-1', Rate.percent( 5 ), Duration( 48, TimeUnit.MONTH ) ) ],
        loan_terms_snapshots = [ LoanTermsSnapshot( 'debt-1', Rate.percent( 6 ), Duration( 48, TimeUnit.MONTH ) ) ] ) )
    return record


class PlansLoanTermsDriftViewTests( TestCase ):
    """The per-loan value-drift reconcile views: reset re-seeds the repayment from the updated contract;
    keep leaves the repayment and refreshes the snapshot. Both are org-scoped and return to the referer."""

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()

    def _post( self, view, name, uuid ):
        request = self.factory.post( reverse( name, kwargs = { 'uuid': uuid, 'handle': 'debt-1' } ) )
        request.organization = self.organization
        return view().post( request, uuid = uuid, handle = 'debt-1' )

    def test_reset_reseeds_the_repayment_from_the_contract( self ):
        profile_record = _profile_with_termed_debt( self.organization, 7 )      # contract now 7%
        record   = _loan_terms_drifted_plans_record( self.organization )
        response = self._post( PlansLoanTermsResetView, 'plans_loan_terms_reset', record.uuid )
        self.assertEqual( response.status_code, 302 )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( plans.loan_repayments[ 0 ].interest_rate, Rate.percent( 7 ) )       # re-seeded
        self.assertEqual( loan_terms_drift( load_profile( profile_record ), plans ), [] )      # cleared

    def test_keep_leaves_the_repayment_and_clears_the_drift( self ):
        profile_record = _profile_with_termed_debt( self.organization, 7 )
        record = _loan_terms_drifted_plans_record( self.organization )
        self._post( PlansLoanTermsKeepView, 'plans_loan_terms_keep', record.uuid )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( plans.loan_repayments[ 0 ].interest_rate, Rate.percent( 5 ) )        # unchanged
        self.assertEqual( loan_terms_drift( load_profile( profile_record ), plans ), [] )      # cleared

    def test_reset_is_a_no_op_without_a_complete_profile( self ):
        # No complete profile: there is no current contract to reconcile against, so the plan is left
        # untouched (repayment and snapshot unchanged) and the view still redirects.
        record   = _loan_terms_drifted_plans_record( self.organization )
        response = self._post( PlansLoanTermsResetView, 'plans_loan_terms_reset', record.uuid )
        self.assertEqual( response.status_code, 302 )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( plans.loan_repayments[ 0 ].interest_rate, Rate.percent( 5 ) )        # unchanged
        self.assertEqual( plans.loan_terms_snapshots[ 0 ].interest_rate, Rate.percent( 6 ) )   # unchanged

    def test_it_is_org_scoped( self ):
        record = _loan_terms_drifted_plans_record( self.organization )
        request = self.factory.post(
            reverse( 'plans_loan_terms_reset', kwargs = { 'uuid': record.uuid, 'handle': 'debt-1' } ) )
        request.organization = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            PlansLoanTermsResetView().post( request, uuid = record.uuid, handle = 'debt-1' )


def _renter_profile( organization, rent = '2500' ):
    """A complete profile that rents, carrying `rent` as its current monthly-rent fact."""
    profile = replace( forecast_profile(), home_tenure = HousingTenure.RENT,
                       home_monthly_rent = Decimal( rent ) )
    record  = save_profile( organization, profile )
    record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                     if flow_of( section ) == 'profile' and section.form is not None ]
    record.save()
    return record


def _rent_drifted_plans_record( organization, profile ):
    """A Plans record whose rented-home rent expense seeded from $2,000 (snapshot $2,000) -- so it drifts
    against a profile whose current rent fact has since moved."""
    record = PlansRecord( organization = organization, label = 'Rent P' )
    seeded = set_home_rent(
        Plans( property_expenses = merged_property_expenses( profile, Plans() ) ), Decimal( '2000' ) )
    save_plans( record, seeded )
    return record


def _rent_amount( plans ):
    return next( e for e in plans.property_expenses if e.handle == RENT_EXPENSE_HANDLE ).default_amount


class PlansHomeRentDriftViewTests( TestCase ):
    """The rented-home rent value-drift reconcile views: reset adopts the current Profile rent into the plan;
    keep leaves the plan's rent and refreshes the snapshot. Both are org-scoped and return to the referer."""

    @classmethod
    def setUpTestData( cls ):
        seed_default_parameter_sets()      # merged_property_expenses reads the seeded catalog

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()

    def _post( self, view, name, uuid ):
        request = self.factory.post( reverse( name, kwargs = { 'uuid': uuid } ) )
        request.organization = self.organization
        return view().post( request, uuid = uuid )

    def test_reset_adopts_the_profile_rent_into_the_plan( self ):
        profile_record = _renter_profile( self.organization, '2500' )        # fact now $2,500
        record   = _rent_drifted_plans_record( self.organization, load_profile( profile_record ) )
        response = self._post( PlansHomeRentResetView, 'plans_home_rent_reset', record.uuid )
        self.assertEqual( response.status_code, 302 )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( _rent_amount( plans ), Decimal( '2500' ) )                             # adopted
        self.assertFalse( home_rent_drift( load_profile( profile_record ), plans ) )             # cleared

    def test_keep_leaves_the_plan_rent_and_clears_the_drift( self ):
        profile_record = _renter_profile( self.organization, '2500' )
        record = _rent_drifted_plans_record( self.organization, load_profile( profile_record ) )
        self._post( PlansHomeRentKeepView, 'plans_home_rent_keep', record.uuid )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( _rent_amount( plans ), Decimal( '2000' ) )                             # unchanged
        self.assertFalse( home_rent_drift( load_profile( profile_record ), plans ) )             # cleared

    def test_reset_is_a_no_op_without_a_complete_profile( self ):
        # No complete profile: there is no current rent to reconcile against, so the plan is left untouched
        # (rent and snapshot unchanged) and the view still redirects.
        renter   = replace( forecast_profile(), home_tenure = HousingTenure.RENT,
                            home_monthly_rent = Decimal( '2500' ) )
        record   = _rent_drifted_plans_record( self.organization, renter )   # never saved as a complete profile
        response = self._post( PlansHomeRentResetView, 'plans_home_rent_reset', record.uuid )
        self.assertEqual( response.status_code, 302 )
        record.refresh_from_db()
        plans = load_plans( record )
        self.assertEqual( _rent_amount( plans ), Decimal( '2000' ) )                             # unchanged
        self.assertEqual( plans.home_rent_snapshot, Decimal( '2000' ) )                          # unchanged

    def test_it_is_org_scoped( self ):
        profile_record = _renter_profile( self.organization, '2500' )
        record  = _rent_drifted_plans_record( self.organization, load_profile( profile_record ) )
        request = self.factory.post( reverse( 'plans_home_rent_reset', kwargs = { 'uuid': record.uuid } ) )
        request.organization = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            PlansHomeRentResetView().post( request, uuid = record.uuid )
