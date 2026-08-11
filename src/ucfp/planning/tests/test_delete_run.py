"""DeleteRunView: removing a saved forecast run from the hub's Saved-runs list.

A saved run is a SAVED `PlanningResultRecord` over a captured `ProjectionRunRecord` and its books; deleting
it must drop the books too (so the list cannot grow unbounded and no orphaned books linger), and must be
scoped -- only this org's SAVED forecast runs, never a transient/working run or another org's.
"""
from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.models import PlanningResultRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile
from ucfp.planning.views import DeleteRunView, RunDiscardConfirmView


class DeleteRunTests( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets', verbosity = 0 )   # expected_assumptions reads a seeded outlook
        self.org     = Organization.objects.create( name = 'Org' )
        self.profile = load_profile( save_profile( self.org, forecast_profile() ) )
        plans        = save_plans( PlansRecord( organization = self.org, label = 'P' ), Plans() )
        assumptions  = save_assumptions(
            AssumptionsRecord( organization = self.org, label = 'A' ), expected_assumptions() )
        self.scenario = load_scenario( create_scenario( self.org, plans, assumptions, 'S' ) )
        self.factory  = RequestFactory()

    def _saved_run( self, usage_role = UsageRole.SAVED ) -> PlanningResultRecord:
        run = run_and_capture(
            organization = self.org, profile = self.profile, plans = self.scenario.plans,
            assumptions = self.scenario.assumptions, frame = forecast_frame(), label = 'S' )
        return PlanningResultRecord.objects.create(
            organization = self.org, feature = PlanningFeature.FINANCIAL_FORECAST,
            run = run, label = 'S', usage_role = usage_role )

    def _delete( self, run_uuid, organization = None ):
        request = self.factory.post( '/delete' )
        request.organization = organization or self.org
        return DeleteRunView().post( request, run_uuid = run_uuid )

    def test_deleting_a_saved_run_drops_the_result_and_its_books( self ):
        result   = self._saved_run()
        books_id = result.run.books_id
        self.assertTrue( BooksOfAccountRecord.objects.filter( pk = books_id ).exists() )

        response = self._delete( result.run.uuid )

        self.assertFalse( PlanningResultRecord.objects.filter( pk = result.pk ).exists() )
        self.assertFalse( BooksOfAccountRecord.objects.filter( pk = books_id ).exists() )   # no orphan
        # deleting (from the hub or the run page's Discard) lands back on the hub
        self.assertEqual( response.status_code, 302 )
        self.assertEqual( response.url, reverse( 'financial_forecast' ) )

    def test_a_working_run_is_not_deletable_here( self ):
        working = self._saved_run( usage_role = UsageRole.WORKING )
        with self.assertRaises( Http404 ):
            self._delete( working.run.uuid )
        self.assertTrue( PlanningResultRecord.objects.filter( pk = working.pk ).exists() )

    def test_another_orgs_run_is_not_deletable( self ):
        result = self._saved_run()
        other  = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._delete( result.run.uuid, organization = other )
        self.assertTrue( PlanningResultRecord.objects.filter( pk = result.pk ).exists() )

    def _confirm( self, run_uuid, organization = None ):
        request = self.factory.get( '/discard-confirm', HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.organization = organization or self.org
        return RunDiscardConfirmView().get( request, run_uuid = run_uuid )

    def test_discard_confirm_modal_names_the_run( self ):
        result = self._saved_run()
        result.run.label = 'Baseline 30yr'
        result.run.save()
        response = self._confirm( result.run.uuid )
        self.assertEqual( response.status_code, 200 )
        self.assertIn( 'Baseline 30yr', response.content.decode() )    # the styled modal, not window.confirm

    def test_discard_confirm_is_scoped_to_the_org( self ):
        result = self._saved_run()
        other  = Organization.objects.create( name = 'Other confirm' )
        with self.assertRaises( Http404 ):
            self._confirm( result.run.uuid, organization = other )
