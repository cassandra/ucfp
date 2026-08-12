"""`branch_destinations` -- the policy for saving an exploration as a NEW scenario. It replaces asking the
user copy-vs-reuse per component: a component that diverged from the anchor is copied (the branch owns the
change, the anchor keeps its value), an unchanged one is reused (sharing the anchor's set, since copying it
would only mint a duplicate). This is the load-bearing rule -- reusing a *changed* component would instead
write the change back into the shared set, which is exactly the "update" the user declined; copying an
unchanged one would create a disallowed duplicate scenario.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.inputs.scenarios.exploration import COPY, OVERWRITE, branch_destinations
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection


def _other_plans() -> Plans:
    return Plans( drawdown = DrawdownPolicy( cash_floor = Decimal( '25000' ) ) )


def _other_assumptions() -> Assumptions:
    return Assumptions( tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


class BranchDestinationsTest( SimpleTestCase ):

    def test_only_the_changed_component_is_copied( self ):
        source  = Scenario( plans = Plans()       , assumptions = Assumptions() )
        working = Scenario( plans = _other_plans(), assumptions = Assumptions() )   # plans diverged
        self.assertEqual(
            branch_destinations( source, working ),
            { 'plans': COPY, 'assumptions': OVERWRITE } )   # copy the change, reuse the unchanged assumptions

    def test_both_changed_components_are_copied( self ):
        source  = Scenario( plans = Plans()       , assumptions = Assumptions() )
        working = Scenario( plans = _other_plans(), assumptions = _other_assumptions() )
        self.assertEqual(
            branch_destinations( source, working ),
            { 'plans': COPY, 'assumptions': COPY } )

    def test_no_change_reuses_both( self ):
        # A degenerate input the modal never actually reaches (it appears only with unsaved changes), but the
        # rule stays well-defined: nothing diverged, so nothing is copied.
        source = Scenario( plans = Plans(), assumptions = Assumptions() )
        self.assertEqual(
            branch_destinations( source, source ),
            { 'plans': OVERWRITE, 'assumptions': OVERWRITE } )
