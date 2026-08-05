"""An organization always keeps at least one Scenario, Plans, and Assumptions.

Much of the app assumes these exist, so the repository refuses to delete the last of each kind, raising
BadRequest (the middleware renders it as a 400). The Scenarios UI already hides the control in that case;
this guards the operation itself against a request that slips through.
"""
from django.core.exceptions import BadRequest
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for, delete_assumptions, save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import delete_plans, plans_for, save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.scenarios.repository import (
    create_scenario, delete_scenario, scenarios_for, would_orphan_all_scenarios )
from ucfp.inputs.views import PlansDeleteView
from ucfp.session_state import SessionState


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


class ComponentCascadeGuardTests( TestCase ):
    """Deleting a Plans or Assumptions set cascades away the scenarios that pair it -- an indirect route to
    zero scenarios that the per-kind guard does not catch (it only counts the components)."""

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

    def test_deleting_a_component_the_only_scenario_uses_would_orphan( self ):
        plans       = self._plans( 'P' )
        assumptions = self._assumptions( 'A' )
        create_scenario( self.organization, plans, assumptions, 'S' )
        self.assertTrue( would_orphan_all_scenarios( self.organization, plans = plans ) )
        self.assertTrue( would_orphan_all_scenarios( self.organization, assumptions = assumptions ) )

    def test_safe_when_another_scenario_survives_the_cascade( self ):
        p1          = self._plans( 'P1' )
        p2          = self._plans( 'P2' )
        assumptions = self._assumptions( 'A' )
        create_scenario( self.organization, p1, assumptions, 'S1' )
        create_scenario( self.organization, p2, assumptions, 'S2' )
        self.assertFalse( would_orphan_all_scenarios( self.organization, plans = p1 ) )

    def test_deleting_an_unused_component_never_orphans( self ):
        used   = self._plans( 'Used' )
        unused = self._plans( 'Unused' )
        create_scenario( self.organization, used, self._assumptions( 'A' ), 'S' )
        self.assertFalse( would_orphan_all_scenarios( self.organization, plans = unused ) )

    def test_plans_delete_view_refuses_a_cascade_that_would_orphan_scenarios( self ):
        plans = self._plans( 'P' )
        self._plans( 'Spare' )                                  # a second set, so the per-kind guard passes
        create_scenario( self.organization, plans, self._assumptions( 'A' ), 'S' )
        request = RequestFactory().post( f'/inputs/plans/{plans.uuid}/delete/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()

        with self.assertRaises( BadRequest ):
            PlansDeleteView().post( request, uuid = plans.uuid )
        self.assertTrue( PlansRecord.objects.filter( pk = plans.pk ).exists() )   # not deleted
