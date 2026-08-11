"""RenameRunView: renaming a captured run from the results page's inline editor.

The run record carries the one label the results page and the hub both show, so a rename updates it
directly. Saves silently; a blank name is ignored; scoped to the org's own runs.
"""
from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile
from ucfp.planning.views import RenameRunView


class RenameRunTests( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets', verbosity = 0 )
        self.org      = Organization.objects.create( name = 'Org' )
        profile       = load_profile( save_profile( self.org, forecast_profile() ) )
        plans         = save_plans( PlansRecord( organization = self.org, label = 'P' ), Plans() )
        assumptions   = save_assumptions(
            AssumptionsRecord( organization = self.org, label = 'A' ), expected_assumptions() )
        scenario      = load_scenario( create_scenario( self.org, plans, assumptions, 'S' ) )
        self.run      = run_and_capture(
            organization = self.org, profile = profile, plans = scenario.plans,
            assumptions = scenario.assumptions, frame = forecast_frame(), label = 'Default Scenario' )
        self.factory  = RequestFactory()

    def _rename( self, run_uuid, label, organization = None ):
        request = self.factory.post( '/rename', { 'label': label } )
        request.organization = organization or self.org
        return RenameRunView().post( request, run_uuid = run_uuid )

    def test_rename_updates_the_run_label( self ):
        self._rename( self.run.uuid, 'Baseline 30yr' )
        self.run.refresh_from_db()
        self.assertEqual( self.run.label, 'Baseline 30yr' )

    def test_a_blank_name_is_ignored( self ):
        self._rename( self.run.uuid, '   ' )
        self.run.refresh_from_db()
        self.assertEqual( self.run.label, 'Default Scenario' )   # unchanged

    def test_another_orgs_run_is_not_renamable( self ):
        other = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._rename( self.run.uuid, 'Sneaky', organization = other )
        self.run.refresh_from_db()
        self.assertEqual( self.run.label, 'Default Scenario' )
