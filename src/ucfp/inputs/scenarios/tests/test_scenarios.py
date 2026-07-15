"""The Scenario record + repository (#87 Phase 1): the JSON round-trip and the working-copy semantics.

A scenario fully owns a copy of its Plans + Assumptions, serialized whole into its record. Runs snapshot
the same pair, so the serialization round-trip pinned here *is* the re-hydration path (loading a saved
scenario, or reconstructing one from a run's embedded inputs) -- it must reproduce the inputs exactly.
The single working copy and its promotion to an independent saved scenario carry the exploration-loop
semantics, so both earn a test.
"""
from decimal import Decimal

from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.inputs.scenarios.repository import (
    create_scenario,
    load_scenario,
    save_working_as_scenario,
    scenarios_for,
    set_working_scenario,
    working_scenario,
)
from ucfp.inputs.scenarios.schemas import Scenario


def _rich_scenario() -> Scenario:
    """A scenario with non-trivial nested inputs (a drawdown policy, a tax projection) to exercise the
    serialization round-trip re-hydration relies on."""
    plans = Plans( drawdown = DrawdownPolicy(
        cash_floor = Decimal( '25000' ), cash_ceiling = Decimal( '50000' ),
        draw_order = [ AssetClass.CDS, AssetClass.BONDS, AssetClass.STOCKS ],
        sweep_allocation = [ ( 'stocks', Decimal( '0.6' ) ), ( 'bonds', Decimal( '0.4' ) ) ] ) )
    assumptions = Assumptions(
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )
    return Scenario( plans = plans, assumptions = assumptions )


class ScenarioRepositoryTest( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def test_scenario_round_trips_through_its_record( self ):
        scenario = _rich_scenario()
        record   = create_scenario( self.organization, scenario, label = 'Base' )
        self.assertEqual( record.usage_role, UsageRole.SAVED )
        self.assertEqual( load_scenario( record ), scenario )   # re-hydration reproduces the inputs exactly

    def test_saved_list_excludes_the_working_copy_and_orders_by_recency( self ):
        first  = create_scenario( self.organization, label = 'First' )
        second = create_scenario( self.organization, label = 'Second' )
        set_working_scenario( self.organization, _rich_scenario() )   # a WORKING copy must not appear
        listed = list( scenarios_for( self.organization ) )
        self.assertEqual( [ record.uuid for record in listed ], [ second.uuid, first.uuid ] )

    def test_working_scenario_is_single_and_overwritten( self ):
        set_working_scenario( self.organization, Scenario() )
        rich = _rich_scenario()
        set_working_scenario( self.organization, rich )
        self.assertEqual(
            self.organization.scenarios.filter( usage_role = UsageRole.WORKING ).count(), 1 )
        self.assertEqual( load_scenario( working_scenario( self.organization ) ), rich )

    def test_promoting_the_working_copy_is_an_independent_save( self ):
        set_working_scenario( self.organization, _rich_scenario() )
        saved = save_working_as_scenario( self.organization, 'Kept' )
        self.assertEqual( saved.usage_role, UsageRole.SAVED )
        self.assertEqual( saved.label, 'Kept' )
        # the saved copy is independent: churning the working copy afterward does not touch it
        set_working_scenario( self.organization, Scenario() )
        self.assertEqual( load_scenario( saved ), _rich_scenario() )
