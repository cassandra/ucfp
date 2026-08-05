"""scenario_started distinguishes a user-built scenario from the auto-created Default.

Setting up the Profile auto-creates a Default scenario, so a never-touched scenario is "in progress"
only by construction. scenario_started keys off whether the user has reviewed any Plans or Assumptions
step, so the forecast gate offers only a genuinely worked-on scenario to resume -- not the Default the
user never chose to build.
"""
import unittest
from types import SimpleNamespace

from ucfp.planning.gating import scenario_started


def _scenario( plans_keys, assumptions_keys ):
    return SimpleNamespace(
        plans       = SimpleNamespace( acknowledged_section_keys = plans_keys ),
        assumptions = SimpleNamespace( acknowledged_section_keys = assumptions_keys ) )


class ScenarioStartedTests( unittest.TestCase ):

    def test_untouched_default_is_not_started( self ):
        self.assertFalse( scenario_started( _scenario( set(), set() ) ) )

    def test_a_reviewed_plans_step_counts_as_started( self ):
        self.assertTrue( scenario_started( _scenario( { 'living-expenses' }, set() ) ) )

    def test_a_reviewed_assumptions_step_counts_as_started( self ):
        self.assertTrue( scenario_started( _scenario( set(), { 'external-factors' } ) ) )
