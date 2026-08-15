"""Input gating for the planning pages.

`input_state`/`InputState` report whether an organization has each of the three inputs (Profile, Plans,
Assumptions) at all -- the existence view a page reads via `InputGatedMixin` (`inputs.mixins`). The gates
this branch's onboarding actually keys on are *completeness*, not existence: `completed_profile` /
`profile_is_complete` (the profile has been walked and is valid) and `completed_plans` /
`completed_assumptions` / `flow_reviewed` (a component's flow has been walked). Scenario-level
run-readiness (across all three inputs) lives one step later in `planning.readiness`/`planning.gating`.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for
from ucfp.inputs.interview import AccountsForm, applicable_sections, flow_of
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.plans.repository import plans_for
from ucfp.inputs.profile.repository import latest_profile, load_profile, profiles_for
from ucfp.inputs.profile.schemas import Profile


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
    plus the profile-level facts a forecast should not silently assume -- a filing status (a person) and a
    housing choice (own/rent/neither, rather than an unanswered `None` the engine would treat as no housing
    cost)."""
    profile = load_profile( record )
    return ( flow_reviewed( profile, record, 'profile' )
             and profile.filing_status is not None
             and profile.home_tenure is not None )


def profile_completion_blockers( record : ProfileRecord ) -> list[ str ]:
    """The hard requirements a *walked* profile still lacks -- shown to explain why it reads incomplete
    once the user has been through every section. Empty while the walk is in progress (the stepper already
    shows what is left, and half-entered data is not an error yet) and empty once complete. The hard data:
    a person (which sets the filing status a run needs) and a housing choice (own/rent/neither, rather than
    an unanswered default the run would silently assume)."""
    profile = load_profile( record )
    if not flow_reviewed( profile, record, 'profile' ):
        return []
    blockers : list[ str ] = []
    if not profile.subjects:
        blockers.append( 'Add at least one person.' )
    if profile.home_tenure is None:
        blockers.append( 'Choose whether you own or rent your home.' )
    return blockers


def profile_advisories( record : ProfileRecord ) -> list[ str ]:
    """Gentle, non-blocking notes for a *complete* profile -- quiet "is this what you meant?" observations,
    not errors and not asks. Gated on completeness, so (like the blockers) nothing shows mid-walk, and it
    never piles onto a profile that still has a real blocker. Today: a complete household with no funded
    account, which reads more as an overlooked section than a fact about their finances."""
    if not profile_is_complete( record ):
        return []
    profile = load_profile( record )
    notes : list[ str ] = []
    if not _has_funded_account( profile ):
        notes.append( 'No account balances entered yet.' )
    return notes


def _has_funded_account( profile : Profile ) -> bool:
    """Whether any financial account (the Accounts section's classes -- cash, investments, retirement) holds
    a positive balance. Home, vehicles, and possessions are their own sections, so they do not count."""
    return any( asset.opening_value for asset in profile.assets
                if asset.asset_class in AccountsForm.ACCOUNT_CLASSES )


def completed_plans( profile_record : ProfileRecord, organization : Organization ) -> list:
    """The organization's Plans sets whose plans-flow sections have all been reviewed -- the ones ready to
    combine into a runnable scenario (pairs with `completed_profile`/`completed_assumptions`).
    `profile_record` supplies the conditional-section context."""
    profile = load_profile( profile_record )
    return [ record for record in plans_for( organization )
             if flow_reviewed( profile, record, 'plans' ) ]


def completed_assumptions( profile_record : ProfileRecord, organization : Organization ) -> list:
    """The organization's Assumptions sets whose assumptions-flow sections have all been reviewed -- the
    ones ready to combine into a runnable scenario."""
    profile = load_profile( profile_record )
    return [ record for record in assumptions_for( organization )
             if flow_reviewed( profile, record, 'assumptions' ) ]


def flow_reviewed( profile : Profile, record, flow : str ) -> bool:
    """Whether `record` has had every applicable, live section of `flow` reviewed -- the completeness a
    component or the profile shares (a scenario's overall run-readiness adds cross-input checks)."""
    acknowledged = record.acknowledged_section_keys
    return all(
        section.key in acknowledged
        for section in applicable_sections( profile )
        if flow_of( section ) == flow and section.form is not None )
