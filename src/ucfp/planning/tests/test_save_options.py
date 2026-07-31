"""`ExploreView._save_options` -- the per-component save default. It is the policy that decides whether an
explicit save overwrites a shared set (propagating to every other scenario that references it) or protects
them with a copy. The default is the load-bearing part: overwrite when the component is private, a copy
when it is shared -- a wrong default silently mutates other scenarios, so it is worth pinning.
"""
from decimal import Decimal

from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.planning.views import ExploreView


class SaveOptionsTest( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )

    def _components( self, label, plans = None ):
        return ( save_plans( PlansRecord( organization = self.organization, label = f'{label}P' ),
                             plans or Plans() ),
                 save_assumptions( AssumptionsRecord( organization = self.organization, label = f'{label}A' ),
                                   Assumptions() ) )

    def test_shared_component_defaults_to_copy_and_flags_divergence( self ):
        plans, assumptions = self._components( 'Shared', Plans( drawdown = DrawdownPolicy(
            cash_floor = Decimal( '1' ) ) ) )
        first = create_scenario( self.organization, plans, assumptions, 'First' )
        create_scenario( self.organization, plans, assumptions, 'Second' )   # shares both with First
        source_inputs = load_scenario( first )
        working = Scenario( plans = Plans(), assumptions = source_inputs.assumptions )   # plans diverged
        options = ExploreView._save_options( first, working, source_inputs )
        self.assertEqual( options[ 'plans' ][ 'shared_with' ], 1 )
        self.assertEqual( options[ 'plans' ][ 'default' ], 'copy' )         # shared -> protective copy
        self.assertTrue( options[ 'plans' ][ 'changed' ] )                  # plans diverged from source
        self.assertFalse( options[ 'assumptions' ][ 'changed' ] )           # assumptions unchanged

    def test_private_component_defaults_to_overwrite( self ):
        plans, assumptions = self._components( 'Solo' )
        solo = create_scenario( self.organization, plans, assumptions, 'Solo' )
        source_inputs = load_scenario( solo )
        options = ExploreView._save_options( solo, source_inputs, source_inputs )
        self.assertEqual( options[ 'plans' ][ 'shared_with' ], 0 )
        self.assertEqual( options[ 'plans' ][ 'default' ], 'overwrite' )    # private -> update in place
