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
from typing import Optional

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.plans.repository import plans_for
from ucfp.inputs.profile.repository import latest_profile, load_profile, profiles_for


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


def completed_profile( organization : Organization ) -> Optional[ ProfileRecord ]:
    """The organization's profile if it is *complete*, else None -- the gate the home page and every
    profile-needing feature use. Mere existence is not enough: entering the profile flow auto-creates an
    empty record, so a profile counts only once every applicable profile-flow section has been reviewed
    and it carries the validity a run needs (a filing status). Parallels the complete-vs-in-progress split
    for scenarios."""
    record = latest_profile( organization )
    if record is None:
        return None
    return record if profile_is_complete( record ) else None


def profile_is_complete( record : ProfileRecord ) -> bool:
    """Whether `record` is a fully set-up profile: every applicable, live profile-flow section reviewed,
    and a filing status present (the one profile-level fact a forecast cannot run without)."""
    profile = load_profile( record )
    return ( _flow_reviewed( profile, record, 'profile' )
             and profile.filing_status is not None )


def complete_plans( profile_record : ProfileRecord, organization : Organization ) -> list:
    """The organization's Plans sets whose plans-flow sections have all been reviewed -- the ones ready to
    combine into a runnable scenario. `profile_record` supplies the conditional-section context."""
    profile = load_profile( profile_record )
    return [ record for record in plans_for( organization )
             if _flow_reviewed( profile, record, 'plans' ) ]


def complete_assumptions( profile_record : ProfileRecord, organization : Organization ) -> list:
    """The organization's Assumptions sets whose assumptions-flow sections have all been reviewed -- the
    ones ready to combine into a runnable scenario."""
    profile = load_profile( profile_record )
    return [ record for record in assumptions_for( organization )
             if _flow_reviewed( profile, record, 'assumptions' ) ]


def _flow_reviewed( profile, record, flow : str ) -> bool:
    """Whether `record` has had every applicable, live section of `flow` reviewed -- the completeness a
    component or the profile shares (a scenario's overall run-readiness adds cross-input checks)."""
    acknowledged = record.acknowledged_section_keys
    return all(
        section.key in acknowledged
        for section in applicable_sections( profile )
        if flow_of( section ) == flow and section.form is not None )
