"""The Scenario record + repository: a scenario *references* a Plans and an Assumptions rather than
copying them. Reference resolution, propagation of a shared-component edit, and the delete cascade are the
behaviours worth pinning here. The WORKING sandbox and its save-back lifecycle are covered in
`test_exploration`.
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
    scenarios_for,
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
            AssumptionsRecord( organization = self.organization, label = 'Assumptions' ),
            _rich_assumptions() )
        return plans, assumptions

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

    def test_deleting_a_referenced_component_cascades_to_its_scenarios( self ):
        plans, assumptions = self._components()
        create_scenario( self.organization, plans, assumptions, label = 'Doomed' )
        plans.delete()
        self.assertFalse( scenarios_for( self.organization ).exists() )   # gone with its Plans
