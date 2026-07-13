"""An organization's input-existence state -- which of the three planning inputs (Profile, Plans,
Assumptions) it has set up, collapsed to the single readiness a gated page keys its guidance on.

Any page that runs a planning feature first needs all three inputs to even exist; before that, the
right guidance differs by how much is set up. `EMPTY` (nothing yet) is the first-time case -- one
link into the guided interview; `PARTIAL` (some but not all) is the surgical case -- name what is
still missing; `READY` (all three) clears this gate, leaving only the chosen-bundle check in
`planning.readiness` between the user and a run. `input_state` builds it for an organization;
`InputGatedMixin` (in `inputs.mixins`) hands it to a view that gates on it.
"""
from dataclasses import dataclass
from enum import Enum

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for
from ucfp.inputs.plans.repository import plans_for
from ucfp.inputs.profile.repository import profiles_for


class InputReadiness( Enum ):
    """How much of the Profile/Plans/Assumptions bundle an organization has -- the axis a gated page
    branches its messaging on. Ordered from nothing set up to all three present."""
    EMPTY   = 'empty'      # none of the three yet -- the first-time case
    PARTIAL = 'partial'    # some but not all -- name what is still missing
    READY   = 'ready'      # all three present -- the existence gate is cleared


@dataclass( frozen = True )
class InputState:
    """Which of the three planning inputs an organization has, and the single `readiness` the pages
    gate on. `readiness` collapses the three flags to EMPTY/PARTIAL/READY; `is_ready` is the common
    check a feature makes before offering its run controls, `is_empty` the first-time greeting."""
    has_profile     : bool
    has_plans       : bool
    has_assumptions : bool

    @property
    def readiness( self ) -> InputReadiness:
        present = ( self.has_profile, self.has_plans, self.has_assumptions )
        if all( present ):
            return InputReadiness.READY
        if any( present ):
            return InputReadiness.PARTIAL
        return InputReadiness.EMPTY

    @property
    def is_empty( self ) -> bool:
        return self.readiness is InputReadiness.EMPTY

    @property
    def is_partial( self ) -> bool:
        return self.readiness is InputReadiness.PARTIAL

    @property
    def is_ready( self ) -> bool:
        return self.readiness is InputReadiness.READY


def input_state( organization : Organization ) -> InputState:
    """The organization's input-existence state -- whether it has at least one Profile, Plans, and
    Assumptions each. The existence gate every input-gated page reads before its own controls;
    distinct from `planning.readiness`, which judges whether a *chosen* bundle is complete."""
    return InputState(
        has_profile     = profiles_for( organization ).exists(),
        has_plans       = plans_for( organization ).exists(),
        has_assumptions = assumptions_for( organization ).exists() )
