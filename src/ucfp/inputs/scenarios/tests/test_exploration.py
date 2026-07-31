"""The `ScenarioExploration` seam: the org's single exploration owns a WORKING scenario copy and
names the SAVED anchor it was seeded from. Entry/ownership, in-place tweaks that leave the anchor alone,
the per-component save (overwrite in place vs copy into a new scenario) with its re-anchor, and the
cascade teardown of the owned copy when the anchor is deleted are the behaviours worth pinning.
"""
from decimal import Decimal

from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord, ScenarioExploration, ScenarioRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.inputs.scenarios.exploration import (
    component_usage,
    enter_exploration,
    overwrite_working,
    save_working,
    scenario_exploration,
    working_scenario,
)
from ucfp.inputs.scenarios.repository import create_scenario, delete_scenario, load_scenario, scenarios_for
from ucfp.inputs.scenarios.schemas import Scenario


def _rich_plans() -> Plans:
    return Plans( drawdown = DrawdownPolicy(
        cash_floor = Decimal( '25000' ), cash_ceiling = Decimal( '50000' ),
        draw_order = [ AssetClass.CDS, AssetClass.BONDS, AssetClass.STOCKS ],
        sweep_allocation = [ ( 'stocks', Decimal( '0.6' ) ), ( 'bonds', Decimal( '0.4' ) ) ] ) )


def _rich_assumptions() -> Assumptions:
    return Assumptions( tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


def _rich_scenario() -> Scenario:
    return Scenario( plans = _rich_plans(), assumptions = _rich_assumptions() )


class ScenarioExplorationTest( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _saved( self, scenario: Scenario, label: str ) -> ScenarioRecord:
        """A SAVED scenario holding `scenario`'s content, for an exploration to anchor to. Components are
        built directly (not via the minting helpers, which pull seeded defaults absent in tests)."""
        plans       = save_plans(
            PlansRecord( organization = self.organization, label = f'{label} plans' ), scenario.plans )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = f'{label} assumptions' ),
            scenario.assumptions )
        return create_scenario( self.organization, plans, assumptions, label )

    def test_entering_creates_an_exploration_owning_a_working_copy_anchored_to_source( self ):
        source      = self._saved( _rich_scenario(), 'Base' )
        exploration = enter_exploration( self.organization, source )
        self.assertEqual( exploration.source_id, source.id )
        self.assertEqual( exploration.working.usage_role, UsageRole.WORKING )
        self.assertEqual( load_scenario( exploration.working ), _rich_scenario() )   # seeded from source
        self.assertEqual( scenario_exploration( self.organization ).id, exploration.id )

    def test_working_sandbox_is_single_and_re_seeded_on_re_entry( self ):
        rich  = self._saved( _rich_scenario(), 'Rich' )
        empty = self._saved( Scenario(), 'Empty' )
        enter_exploration( self.organization, empty )
        enter_exploration( self.organization, rich )
        self.assertEqual(
            self.organization.scenarios.filter( usage_role = UsageRole.WORKING ).count(), 1 )
        self.assertEqual( ScenarioExploration.objects.filter( organization = self.organization ).count(), 1 )
        self.assertEqual( load_scenario( working_scenario( self.organization ) ), _rich_scenario() )
        self.assertEqual( scenario_exploration( self.organization ).source_id, rich.id )

    def test_saved_list_excludes_the_working_sandbox( self ):
        first  = self._saved( _rich_scenario(), 'First' )
        second = self._saved( _rich_scenario(), 'Second' )
        enter_exploration( self.organization, first )
        self.assertEqual(
            [ record.uuid for record in scenarios_for( self.organization ) ], [ second.uuid, first.uuid ] )

    def test_overwrite_working_changes_the_sandbox_but_not_the_anchor( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )             # tweak the sandbox to empty
        self.assertEqual( load_scenario( working_scenario( self.organization ) ), Scenario() )
        self.assertEqual( scenario_exploration( self.organization ).source_id, source.id )   # anchor kept
        self.assertEqual( load_scenario( source ), _rich_scenario() )                # source untouched

    def test_save_working_all_overwrite_updates_the_source_in_place( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )            # tweak the sandbox to empty
        result = save_working(
            self.organization, source, { 'plans': 'overwrite', 'assumptions': 'overwrite' } )
        self.assertEqual( result.pk, source.pk )                     # same scenario, no new one minted
        self.assertEqual( scenarios_for( self.organization ).count(), 1 )
        reloaded = scenarios_for( self.organization ).get( uuid = source.uuid )
        self.assertEqual( load_scenario( reloaded ), Scenario() )     # source's own sets now hold the values

    def test_save_working_all_copy_branches_an_independent_scenario( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )
        result = save_working(
            self.organization, source, { 'plans': 'copy', 'assumptions': 'copy' }, 'Test' )
        self.assertNotEqual( result.pk, source.pk )                  # a new scenario...
        self.assertNotEqual( result.plans_id, source.plans_id )      # ...with independent components
        self.assertNotEqual( result.assumptions_id, source.assumptions_id )
        self.assertEqual(                                            # copies are SAVED sets, no WORKING leak
            PlansRecord.objects.get( pk = result.plans_id ).usage_role, UsageRole.SAVED )
        self.assertEqual( load_scenario( source ), _rich_scenario() )   # source untouched
        self.assertEqual( scenario_exploration( self.organization ).source_id, result.id )   # re-anchored

    def test_save_working_copy_dedupes_new_component_names_and_defaults_a_blank_name( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )
        both = { 'plans': 'copy', 'assumptions': 'copy' }
        first = save_working( self.organization, source, both, 'Test' )
        enter_exploration( self.organization, source )               # a fresh exploration, same anchor
        overwrite_working( self.organization, Scenario() )
        second = save_working( self.organization, source, both, 'Test' )
        self.assertEqual( PlansRecord.objects.get( pk = first.plans_id ).label, 'Test Plans' )
        self.assertEqual(                                           # a colliding copy name is deduped
            PlansRecord.objects.get( pk = second.plans_id ).label, 'Test Plans 2' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )
        blank = save_working( self.organization, source, both )      # no name
        self.assertEqual( blank.label, 'Base copy' )                # unnamed save -> a "<source> copy"
        self.assertEqual(                                          # and the copied set is named to match
            PlansRecord.objects.get( pk = blank.plans_id ).label, 'Base copy Plans' )

    def test_save_working_mixed_branches_but_shares_the_overwritten_component( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working(                                           # change only the Plans
            self.organization, Scenario( plans = Plans(), assumptions = _rich_assumptions() ) )
        result = save_working(
            self.organization, source, { 'plans': 'copy', 'assumptions': 'overwrite' }, 'Test' )
        self.assertNotEqual( result.pk, source.pk )                  # a new scenario,
        self.assertNotEqual( result.plans_id, source.plans_id )      # its copied Plans is independent,
        self.assertEqual( result.assumptions_id, source.assumptions_id )   # its Assumptions shared w/ source

    def test_component_usage_counts_other_scenarios_sharing_a_component( self ):
        plans       = save_plans(
            PlansRecord( organization = self.organization, label = 'P' ), _rich_plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'A' ), _rich_assumptions() )
        first = create_scenario( self.organization, plans, assumptions, 'First' )
        create_scenario( self.organization, plans, assumptions, 'Second' )   # shares both with First
        usage = component_usage( first )
        self.assertEqual( usage[ 'plans' ], 1 )                      # one other scenario references each,
        self.assertEqual( usage[ 'assumptions' ], 1 )
        solo = self._saved( _rich_scenario(), 'Solo' )
        self.assertEqual( component_usage( solo )[ 'plans' ], 0 )    # a private component: no others

    def test_deleting_the_anchor_cascades_and_tears_down_the_owned_working_copy( self ):
        source      = self._saved( _rich_scenario(), 'Base' )
        exploration = enter_exploration( self.organization, source )
        working_id, plans_id, assumptions_id = (
            exploration.working_id, exploration.working.plans_id, exploration.working.assumptions_id )
        delete_scenario( source )
        self.assertFalse( ScenarioExploration.objects.filter( organization = self.organization ).exists() )
        self.assertFalse( ScenarioRecord.objects.filter( pk = working_id ).exists() )
        self.assertFalse( PlansRecord.objects.filter( pk = plans_id ).exists() )         # owned copy gone
        self.assertFalse( AssumptionsRecord.objects.filter( pk = assumptions_id ).exists() )
