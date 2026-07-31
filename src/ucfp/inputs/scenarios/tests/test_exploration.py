"""The `ScenarioExploration` seam: the org's single exploration owns a WORKING scenario copy and
names the SAVED anchor it was seeded from. Entry/ownership, in-place tweaks that leave the anchor alone,
Update/Save-as-new write-back, re-anchoring on Save-as-new, and the cascade teardown of the owned copy
when the anchor is deleted are the behaviours worth pinning.
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
    enter_exploration,
    overwrite_working,
    save_working_as_scenario,
    save_working_over_scenario,
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

    def test_update_writes_the_sandbox_into_the_anchor_components( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )
        save_working_over_scenario( self.organization, source )
        reloaded = scenarios_for( self.organization ).get( uuid = source.uuid )
        self.assertEqual( load_scenario( reloaded ), Scenario() )      # written into the shared refs

    def test_save_as_new_forks_only_the_changed_component( self ):
        source = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working(                                            # change only the Plans
            self.organization, Scenario( plans = Plans(), assumptions = _rich_assumptions() ) )
        variant = save_working_as_scenario( self.organization, 'Variant', source )
        self.assertEqual( variant.usage_role, UsageRole.SAVED )
        self.assertNotEqual( variant.plans_id, source.plans_id )      # the changed Plans is forked...
        self.assertEqual( variant.assumptions_id, source.assumptions_id )   # ...the unchanged one is shared
        forked_plans = PlansRecord.objects.get( pk = variant.plans_id )   # re-fetched, not the clone
        self.assertEqual( forked_plans.usage_role, UsageRole.SAVED )  # a user-facing set, not a WORKING leak
        self.assertEqual( load_scenario( variant ).plans, Plans() )

    def test_save_as_new_shares_both_components_when_nothing_changed( self ):
        source  = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        variant = save_working_as_scenario( self.organization, 'Variant', source )
        self.assertEqual( variant.plans_id, source.plans_id )
        self.assertEqual( variant.assumptions_id, source.assumptions_id )

    def test_save_as_new_forks_both_components_when_both_changed( self ):
        source  = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )            # both diverge to empty
        variant = save_working_as_scenario( self.organization, 'Variant', source )
        self.assertNotEqual( variant.plans_id, source.plans_id )      # both changed -> both forked
        self.assertNotEqual( variant.assumptions_id, source.assumptions_id )

    def test_save_as_new_re_anchors_the_exploration_to_the_new_scenario( self ):
        source  = self._saved( _rich_scenario(), 'Base' )
        enter_exploration( self.organization, source )
        overwrite_working( self.organization, Scenario() )
        variant = save_working_as_scenario( self.organization, 'Variant', source )
        self.assertEqual( scenario_exploration( self.organization ).source_id, variant.id )

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
