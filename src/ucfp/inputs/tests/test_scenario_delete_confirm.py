"""ScenarioDeleteConfirmView: the styled confirm dialog shown before deleting a scenario.

Renders the app's modal (naming the scenario) rather than a browser window.confirm, and is scoped to the
org's own saved scenarios. The delete itself is ScenarioDeleteView, covered separately.
"""
from django.http import Http404
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.views import ScenarioDeleteConfirmView


class ScenarioDeleteConfirmTests( TestCase ):

    def setUp( self ):
        self.org    = Organization.objects.create( name = 'Org' )
        plans       = PlansRecord( organization = self.org, label = 'P' )
        save_plans( plans, Plans() )
        assumptions = AssumptionsRecord( organization = self.org, label = 'A' )
        save_assumptions( assumptions, Assumptions() )
        self.scenario = create_scenario( self.org, plans, assumptions, 'Retirement plan' )
        self.factory  = RequestFactory()

    def _confirm( self, uuid, organization = None ):
        request = self.factory.get( '/delete-confirm', HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.organization = organization or self.org
        return ScenarioDeleteConfirmView().get( request, uuid = uuid )

    def test_confirm_modal_names_the_scenario( self ):
        response = self._confirm( self.scenario.uuid )
        self.assertEqual( response.status_code, 200 )
        self.assertIn( 'Retirement plan', response.content.decode() )   # the styled modal, not window.confirm

    def test_confirm_is_scoped_to_the_org( self ):
        other = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._confirm( self.scenario.uuid, organization = other )
