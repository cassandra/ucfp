"""Tearing down an exploration: when a saved scenario that anchors an in-progress exploration is
deleted, the exploration cascades away -- and with it the owned working input copies (the inputs-side
receiver) and the transient WORKING runs it produced (the planning-side receiver). The transient runs
carry heavy books, so they must not linger. The teardown must also run cleanly during a whole-organization
delete, where the org's own cascade removes those runs too.
"""
from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import AssumptionsRecord, PlansRecord, ScenarioExploration, ScenarioRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.exploration import enter_exploration
from ucfp.inputs.scenarios.repository import create_scenario, delete_scenario
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.explore import run_working_scenario
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord

from .support import expected_assumptions, forecast_frame, forecast_profile


class ExplorationTeardownTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.organization = Organization.objects.create( name = 'Org' )

    def _anchor_with_a_running_exploration( self ) -> ScenarioRecord:
        """A saved anchor scenario, an exploration seeded from it, and one captured transient run (with its
        books), so the teardown has real WORKING runs to clear."""
        save_profile( self.organization, forecast_profile() )
        plans_record       = save_plans(
            PlansRecord( organization = self.organization, label = 'Plans' ), Plans() )
        assumptions_record = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'Assumptions' ),
            expected_assumptions() )
        anchor = create_scenario( self.organization, plans_record, assumptions_record, 'Anchor' )
        enter_exploration( self.organization, anchor )
        run_working_scenario( self.organization, forecast_frame() )
        return anchor

    def test_deleting_the_anchor_clears_the_exploration_and_its_transient_runs( self ):
        anchor = self._anchor_with_a_running_exploration()
        # A second saved scenario so deleting the anchor is allowed (the last scenario cannot be deleted).
        create_scenario(
            self.organization,
            save_plans( PlansRecord( organization = self.organization, label = 'Other Plans' ), Plans() ),
            save_assumptions(
                AssumptionsRecord( organization = self.organization, label = 'Other Assumptions' ),
                expected_assumptions() ),
            'Other' )
        self.assertEqual(
            PlanningResultRecord.objects.filter( usage_role = UsageRole.WORKING ).count(), 1 )
        self.assertTrue( BooksOfAccountRecord.objects.exists() )          # the run really produced books

        delete_scenario( anchor )

        self.assertEqual( ScenarioExploration.objects.count(), 0 )        # cascaded with its anchor
        self.assertEqual(                                                # owned working copy gone (inputs)
            ScenarioRecord.objects.filter( usage_role = UsageRole.WORKING ).count(), 0 )
        self.assertEqual(                                                # transient runs gone (planning side)
            PlanningResultRecord.objects.filter( usage_role = UsageRole.WORKING ).count(), 0 )
        self.assertEqual( ProjectionRunRecord.objects.count(), 0 )
        self.assertEqual( BooksOfAccountRecord.objects.count(), 0 )       # their heavy books do not linger

    def test_deleting_the_org_with_a_running_exploration_erases_everything( self ):
        # The exploration's post_delete receiver fires mid-cascade here; this pins that it runs without
        # error and leaves nothing behind (it does not force the books-already-gone ordering the bulk
        # delete guards against -- that intermediate state is internal to Django's collector).
        self._anchor_with_a_running_exploration()
        self.assertEqual( ScenarioExploration.objects.count(), 1 )
        self.assertTrue( BooksOfAccountRecord.objects.exists() )

        self.organization.delete()

        self.assertEqual( Organization.objects.count(), 0 )              # no error, and nothing remains
        self.assertEqual( ScenarioExploration.objects.count(), 0 )
        self.assertEqual( ScenarioRecord.objects.count(), 0 )
        self.assertEqual( PlanningResultRecord.objects.count(), 0 )
        self.assertEqual( ProjectionRunRecord.objects.count(), 0 )
        self.assertEqual( BooksOfAccountRecord.objects.count(), 0 )
