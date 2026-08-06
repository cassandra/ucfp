"""`clone_scenario` and orphaned-component cleanup.

`clone_scenario` builds a new scenario from an existing one, copying the chosen side(s) and reusing the
other -- the model behind the New scenario page's "Copy" path. Deleting a scenario now also removes any
Plans/Assumptions it leaves paired to no scenario, since a component exists only to serve scenarios.
Components are built directly from empty schemas (not the minting helpers, which pull seeded defaults).
"""
from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.scenarios.repository import clone_scenario, create_scenario, delete_scenario


class _ScenarioFixture( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _plans( self, label, acknowledged = () ):
        record = PlansRecord(
            organization = self.organization, label = label, acknowledged_sections = list( acknowledged ) )
        save_plans( record, Plans() )
        return record

    def _assumptions( self, label, acknowledged = () ):
        record = AssumptionsRecord(
            organization = self.organization, label = label, acknowledged_sections = list( acknowledged ) )
        save_assumptions( record, Assumptions() )
        return record

    def _scenario( self, label, plans = None, assumptions = None ):
        return create_scenario(
            self.organization, plans or self._plans( f'{label} P' ),
            assumptions or self._assumptions( f'{label} A' ), label )


class CloneScenarioTests( _ScenarioFixture ):

    def test_copy_both_clones_each_side( self ):
        source = self._scenario( 'Base' )
        clone  = clone_scenario( source, copy_plans = True, copy_assumptions = True, label = 'Copy' )
        self.assertNotEqual( clone.plans_id, source.plans_id )             # both sides are fresh clones
        self.assertNotEqual( clone.assumptions_id, source.assumptions_id )
        self.assertEqual( clone.label, 'Copy' )

    def test_reuse_one_side_shares_that_component( self ):
        source = self._scenario( 'Base' )
        clone  = clone_scenario( source, copy_plans = False, copy_assumptions = True )
        self.assertEqual( clone.plans_id, source.plans_id )               # Plans reused (shared)
        self.assertNotEqual( clone.assumptions_id, source.assumptions_id )  # Assumptions cloned

    def test_a_copied_component_starts_reviewed_from_the_source( self ):
        source = self._scenario( 'Base', plans = self._plans( 'P', acknowledged = [ 'sec-a', 'sec-b' ] ) )
        clone  = clone_scenario( source, copy_plans = True, copy_assumptions = False )
        self.assertEqual( clone.plans.acknowledged_section_keys, { 'sec-a', 'sec-b' } )

    def test_copying_neither_side_is_rejected( self ):
        source = self._scenario( 'Base' )
        with self.assertRaises( ValueError ):
            clone_scenario( source, copy_plans = False, copy_assumptions = False )


class OrphanCleanupTests( _ScenarioFixture ):

    def test_deleting_a_scenario_removes_its_orphaned_components( self ):
        keep   = self._scenario( 'Keep' )                  # a second scenario, so the delete is allowed
        doomed = self._scenario( 'Doomed' )
        plans_pk, assumptions_pk = doomed.plans_id, doomed.assumptions_id

        delete_scenario( doomed )

        self.assertFalse( PlansRecord.objects.filter( pk = plans_pk ).exists() )
        self.assertFalse( AssumptionsRecord.objects.filter( pk = assumptions_pk ).exists() )
        self.assertTrue( PlansRecord.objects.filter( pk = keep.plans_id ).exists() )   # keep's untouched

    def test_a_component_shared_with_another_scenario_survives( self ):
        shared = self._plans( 'Shared' )
        s1     = self._scenario( 'S1', plans = shared )
        s2     = self._scenario( 'S2', plans = shared )
        s1_assumptions_pk = s1.assumptions_id

        delete_scenario( s1 )

        self.assertTrue( PlansRecord.objects.filter( pk = shared.pk ).exists() )        # still used by s2
        self.assertFalse( AssumptionsRecord.objects.filter( pk = s1_assumptions_pk ).exists() )  # orphaned
        self.assertTrue( AssumptionsRecord.objects.filter( pk = s2.assumptions_id ).exists() )
