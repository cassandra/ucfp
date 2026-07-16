"""The Scenario record + repository (#89): a scenario *references* a Plans and an Assumptions rather than
copying them. Reference resolution, propagation of a shared-component edit, the single working sandbox,
the save-as-new fork into independent components, and the delete cascade are the behaviours worth pinning.
"""
from decimal import Decimal

from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.inputs.scenarios.repository import (
    create_scenario,
    load_scenario,
    save_working_as_scenario,
    save_working_over_scenario,
    scenarios_for,
    set_working_scenario,
    working_scenario,
)
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


class ScenarioRepositoryTest( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _components( self ):
        """A SAVED Plans and Assumptions record holding rich content, for a scenario to reference. Built
        directly (not via the minting helpers, which pull seeded parameter-set defaults absent in tests)."""
        plans       = save_plans(
            PlansRecord( organization = self.organization, label = 'Plans' ), _rich_plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = 'Assumptions' ), _rich_assumptions() )
        return plans, assumptions

    def _reload( self, record ):
        return scenarios_for( self.organization ).get( uuid = record.uuid )

    def test_scenario_resolves_its_referenced_components( self ):
        plans, assumptions = self._components()
        record = create_scenario( self.organization, plans, assumptions, label = 'Base' )
        self.assertEqual( record.usage_role, UsageRole.SAVED )
        self.assertEqual( load_scenario( record ), _rich_scenario() )   # resolved from the live components

    def test_editing_a_shared_component_propagates_to_referencing_scenarios( self ):
        plans, assumptions = self._components()
        create_scenario( self.organization, plans, assumptions, label = 'One' )
        create_scenario( self.organization, plans, assumptions, label = 'Two' )
        save_plans( plans, Plans() )                                    # refine the shared Plans
        for record in scenarios_for( self.organization ):              # re-fetched from the DB
            self.assertEqual( load_scenario( record ).plans, Plans() )  # both reflect it -- no copies

    def test_saved_list_excludes_the_working_sandbox_and_orders_by_recency( self ):
        plans, assumptions = self._components()
        first  = create_scenario( self.organization, plans, assumptions, label = 'First' )
        second = create_scenario( self.organization, plans, assumptions, label = 'Second' )
        set_working_scenario( self.organization, _rich_scenario() )    # the sandbox must not appear
        listed = list( scenarios_for( self.organization ) )
        self.assertEqual( [ record.uuid for record in listed ], [ second.uuid, first.uuid ] )

    def test_working_sandbox_is_single_and_overwritten( self ):
        set_working_scenario( self.organization, Scenario() )
        set_working_scenario( self.organization, _rich_scenario() )
        self.assertEqual(
            self.organization.scenarios.filter( usage_role = UsageRole.WORKING ).count(), 1 )
        self.assertEqual( load_scenario( working_scenario( self.organization ) ), _rich_scenario() )

    def test_update_writes_the_sandbox_into_the_referenced_components( self ):
        plans, assumptions = self._components()
        scenario = create_scenario( self.organization, plans, assumptions, label = 'Base' )
        set_working_scenario( self.organization, Scenario() )          # sandbox diverges to empty
        save_working_over_scenario( self.organization, scenario )
        self.assertEqual( load_scenario( self._reload( scenario ) ), Scenario() )   # written into the refs

    def test_save_as_new_forks_only_the_changed_component( self ):
        plans, assumptions = self._components()
        source = create_scenario( self.organization, plans, assumptions, label = 'Base' )
        set_working_scenario( self.organization, load_scenario( source ) )   # enter the sandbox...
        set_working_scenario(                                               # ...then change only the Plans
            self.organization, Scenario( plans = Plans(), assumptions = _rich_assumptions() ) )
        variant = save_working_as_scenario( self.organization, 'Variant', source )
        self.assertEqual( variant.usage_role, UsageRole.SAVED )
        self.assertNotEqual( variant.plans_id, source.plans_id )       # the changed Plans is forked...
        self.assertEqual( variant.assumptions_id, source.assumptions_id )   # ...the unchanged one is shared
        self.assertEqual( variant.plans.usage_role, UsageRole.SAVED )  # the fork is a user-facing set
        self.assertEqual( load_scenario( self._reload( variant ) ).plans, Plans() )

    def test_deleting_a_referenced_component_cascades_to_its_scenarios( self ):
        plans, assumptions = self._components()
        create_scenario( self.organization, plans, assumptions, label = 'Doomed' )
        plans.delete()
        self.assertFalse( scenarios_for( self.organization ).exists() )   # gone with its Plans
