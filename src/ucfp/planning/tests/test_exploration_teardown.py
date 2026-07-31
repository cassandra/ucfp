"""Tearing down an exploration (#92): when a saved scenario that anchors an in-progress exploration is
deleted, the exploration cascades away -- and with it the owned working input copies (the inputs-side
receiver) and the transient WORKING runs it produced (the planning-side receiver). The transient runs
carry heavy books, so they must not linger. The teardown must also survive a whole-organization delete,
where the org cascade removes the same runs concurrently.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import AssumptionsRecord, PlansRecord, ScenarioExploration, ScenarioRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.inputs.scenarios.exploration import enter_exploration
from ucfp.inputs.scenarios.repository import create_scenario, delete_scenario
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.explore import run_working_scenario
from ucfp.planning.materialization import ForecastFrame
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord


class ExplorationTeardownTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )

    def _anchor_with_a_running_exploration( self ) -> ScenarioRecord:
        """A saved anchor scenario, an exploration seeded from it, and one captured transient run (with its
        books), so the teardown has real WORKING runs to clear."""
        profile = Profile(
            subjects = [ SubjectProfile(
                handle = 'subject', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [
                AssetProfile(
                    handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                    opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ),
                AssetProfile(
                    handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                    opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ),
                AssetProfile(
                    handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                    opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )
        save_profile( self.organization, profile )
        assumptions = Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )
        plans_record       = save_plans(
            PlansRecord( organization = self.organization, label = 'Plans' ), Plans() )
        assumptions_record = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'Assumptions' ), assumptions )
        anchor = create_scenario( self.organization, plans_record, assumptions_record, 'Anchor' )
        enter_exploration( self.organization, anchor )
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        run_working_scenario( self.organization, frame )
        return anchor

    def test_deleting_the_anchor_clears_the_exploration_and_its_transient_runs( self ):
        anchor = self._anchor_with_a_running_exploration()
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
        self._anchor_with_a_running_exploration()
        self.assertEqual( ScenarioExploration.objects.count(), 1 )
        self.assertTrue( BooksOfAccountRecord.objects.exists() )

        self.organization.delete()      # the planning receiver and the org cascade both remove the runs

        self.assertEqual( Organization.objects.count(), 0 )              # no crash, and nothing remains
        self.assertEqual( ScenarioExploration.objects.count(), 0 )
        self.assertEqual( ScenarioRecord.objects.count(), 0 )
        self.assertEqual( PlanningResultRecord.objects.count(), 0 )
        self.assertEqual( ProjectionRunRecord.objects.count(), 0 )
        self.assertEqual( BooksOfAccountRecord.objects.count(), 0 )
