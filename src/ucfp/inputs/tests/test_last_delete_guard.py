"""An organization always keeps at least one Scenario, Plans, and Assumptions.

Much of the app assumes these exist, so the repository refuses to delete the last of each kind, raising
BadRequest (the middleware renders it as a 400). The Scenarios UI already hides the control in that case;
this guards the operation itself against a request that slips through.
"""
from django.core.exceptions import BadRequest
from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for, delete_assumptions, save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import delete_plans, plans_for, save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.scenarios.repository import create_scenario, delete_scenario, scenarios_for


class LastDeleteGuardTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _plans( self, label ):
        record = PlansRecord( organization = self.organization, label = label )
        save_plans( record, Plans() )
        return record

    def _assumptions( self, label ):
        record = AssumptionsRecord( organization = self.organization, label = label )
        save_assumptions( record, Assumptions() )
        return record

    def _scenario( self, label ):
        return create_scenario(
            self.organization, self._plans( f'{label} P' ), self._assumptions( f'{label} A' ), label = label )

    def test_cannot_delete_the_last_scenario( self ):
        only = self._scenario( 'Only' )
        with self.assertRaises( BadRequest ):
            delete_scenario( only )
        self.assertEqual( scenarios_for( self.organization ).count(), 1 )

    def test_can_delete_a_scenario_when_another_remains( self ):
        first = self._scenario( 'One' )
        self._scenario( 'Two' )
        delete_scenario( first )
        self.assertEqual( scenarios_for( self.organization ).count(), 1 )

    def test_cannot_delete_the_last_plans( self ):
        only = self._plans( 'Only' )
        with self.assertRaises( BadRequest ):
            delete_plans( only )
        self.assertEqual( plans_for( self.organization ).count(), 1 )

    def test_can_delete_plans_when_another_remains( self ):
        first = self._plans( 'One' )
        self._plans( 'Two' )
        delete_plans( first )
        self.assertEqual( plans_for( self.organization ).count(), 1 )

    def test_cannot_delete_the_last_assumptions( self ):
        only = self._assumptions( 'Only' )
        with self.assertRaises( BadRequest ):
            delete_assumptions( only )
        self.assertEqual( assumptions_for( self.organization ).count(), 1 )

    def test_can_delete_assumptions_when_another_remains( self ):
        first = self._assumptions( 'One' )
        self._assumptions( 'Two' )
        delete_assumptions( first )
        self.assertEqual( assumptions_for( self.organization ).count(), 1 )
