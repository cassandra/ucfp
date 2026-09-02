"""Prefill for the Social Security claiming calculator's inputs form.

The form works for anyone, but no one should retype what a prior visit or a saved Profile already holds.
This resolves the form's initial values, best-effort and read-only, from the highest-priority source that
has each part:

- People are prefilled best effort, field by field: each field takes the saved Profile's value where it
  has one (people are facts, so the Profile wins -- birth year and PIA per person; it has no home for the
  expected lifetime), else this session's `SessionFacts` (which fills the expected lifetime, and any field
  the Profile lacks), else blank. So a prior session entry never overrides a saved fact, but still supplies
  what the Profile cannot.
- Assumptions are "what if" knobs, not facts, so this session's stored run assumptions come first
  (`ss_timing_assumptions` -- the last set used), else the visitor's current scenario's economics, then
  their most recent saved scenario's, then the seeded system defaults.

Anonymous visitors -- and signed-in ones with no profile -- fall through to `SessionFacts` (or blank) for
people and the system defaults for assumptions. Nothing here writes: the form never changes saved data.
"""
from dataclasses import dataclass

from organization.models import OrganizationMember

from ucfp.inputs.assumptions.defaults import default_economics
from ucfp.inputs.assumptions.repository import load_assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import ScenarioRecord
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.scenarios.repository import latest_scenario

from .compute import Assumptions
from .forms import HOUSEHOLD_COUPLE, HOUSEHOLD_SINGLE, default_inputs


@dataclass( frozen = True )
class Prefill:
    """The form's resolved starting point: the field `initial` map -- the people (merged Profile-then-
    session), the economic assumptions, and the household kind."""

    initial : dict


def build_prefill( request ) -> Prefill:
    """The form's initial values for `request`: the people merged field by field from a signed-in visitor's
    Profile then this session's facts (blank for a fresh anonymous visit); the assumptions from this
    session, else a scenario, else the system defaults. Best-effort -- any missing piece falls back rather
    than failing, since the calculator must open for anyone."""
    organization      = _organization( request )
    initial           = dict( _economics_initial( request, organization ) )
    people, household = _people( request, organization )
    initial.update( people )
    initial[ 'household' ] = household
    return Prefill( initial = initial )


def _economics_initial( request, organization ) -> dict:
    """The assumption fields' initial values: this session's stored run assumptions first (re-prefilled
    exactly), else the fields seeded from a scenario or the system defaults."""
    stored = request.session_state.ss_timing_assumptions
    if stored:
        return stored
    return default_inputs( _assumptions( _scenario_economics( request, organization ) ) )


def _people( request, organization ) -> tuple[ dict, str ]:
    """The people fields and the household kind. Best effort and field by field: each field takes the
    Profile's value where it has one -- people are facts, so the Profile wins and a prior "what if" session
    entry never overrides it -- else this session's `SessionFacts` (which also carries the expected lifetime
    the Profile has no home for), else blank. The household kind follows the Profile when it holds people,
    else the session, else the couple default."""
    facts                                           = request.session_state.session_facts
    profile_fields, profile_household, from_profile = _people_from_profile( _profile( organization ) )
    facts_fields, facts_household                   = _people_from_facts( facts )
    initial = dict( facts_fields )
    initial.update( profile_fields )            # a Profile value wins each field it has; facts fill the rest
    if from_profile:
        household = profile_household
    elif facts.people:
        household = facts_household
    else:
        household = HOUSEHOLD_COUPLE            # the blank-form default
    return initial, household


def _people_from_facts( facts ) -> tuple[ dict, str ]:
    """The people fields from this session's facts -- each person's birth year, PIA, expected lifetime, sex,
    and longevity setback, whatever was entered -- and the household kind by whether a partner is present."""
    initial = dict()
    for index, person in enumerate( facts.people[ :2 ] ):
        if person.birth_year is not None:
            initial[ f's{index}_birth_year' ] = person.birth_year
        if person.government_pension_monthly is not None:
            initial[ f's{index}_pia' ] = str( person.government_pension_monthly )
        if person.life_expectancy is not None:
            initial[ f's{index}_life' ] = person.life_expectancy
        if person.sex is not None:
            initial[ f's{index}_sex' ] = person.sex
        if person.longevity_setback is not None:
            initial[ f's{index}_longevity' ] = str( person.longevity_setback )
    household = HOUSEHOLD_COUPLE if facts.is_couple else HOUSEHOLD_SINGLE
    return initial, household


def _organization( request ):
    """The organization the prefill reads from: the one the session currently has selected (so switching
    households changes what prefills), else the visitor's default landing org. Resolves the selection the
    same membership-checked way `ensure_organization` does (`active_membership_for`), but non-creating and
    tolerant of no user -- prefill must open for anyone and never provisions an organization."""
    user = request.user
    if not user.is_authenticated:
        return None
    selected_uuid = request.session_state.current_organization_uuid
    if selected_uuid is not None:
        membership = OrganizationMember.objects.active_membership_for( user, selected_uuid )
        if membership is not None:
            return membership.organization
    return OrganizationMember.objects.default_organization_for( user )


def _profile( organization ):
    if organization is None:
        return None
    record = latest_profile( organization )
    return load_profile( record ) if record is not None else None


def _people_from_profile( profile ) -> tuple[ dict, str, bool ]:
    """The people fields from a saved Profile: each person's birth year and PIA (the expected lifetime is
    left blank -- not a Profile fact yet), the household kind by whether there is a partner, and whether any
    were prefilled (`from_profile`, used to choose the household kind). Blank people and a couple default
    when there is no profile."""
    if profile is None or not profile.subjects:
        return {}, HOUSEHOLD_COUPLE, False
    pia_by_handle = {
        entitlement.subject_handle: entitlement.monthly_at_normal_age
        for entitlement in profile.government_pension }
    initial = dict()
    for index, subject in enumerate( profile.subjects[ :2 ] ):
        initial[ f's{index}_birth_year' ] = subject.birthdate.year
        pia = pia_by_handle.get( subject.handle )
        if pia is not None:
            initial[ f's{index}_pia' ] = str( pia )
    household = HOUSEHOLD_COUPLE if len( profile.subjects ) >= 2 else HOUSEHOLD_SINGLE
    return initial, household, True


def _scenario_economics( request, organization ):
    """The economic parameters to seed the assumptions from: the current scenario's, else the most recent
    saved scenario's, else the system defaults. A scenario carrying no economics falls through to the
    defaults too."""
    if organization is None:
        return default_economics()
    record = _current_scenario( request, organization ) or latest_scenario( organization )
    if record is not None:
        economics = load_assumptions( record.assumptions ).economics
        if economics is not None:
            return economics
    return default_economics()


def _current_scenario( request, organization ):
    """The visitor's currently-selected saved scenario, or None -- a stale/absent selection just falls
    back to the most recent."""
    scenario_uuid = request.session_state.current_scenario_uuid
    if not scenario_uuid:
        return None
    return ScenarioRecord.objects.filter(
        uuid = scenario_uuid, organization = organization, usage_role = UsageRole.SAVED ).first()


def _assumptions( economics ) -> Assumptions:
    """The calculator's `Assumptions` from a run's `EconomicParameters` -- the discount is the general
    inflation the present value discounts at."""
    return Assumptions(
        inflation        = economics.inflation,
        cola             = economics.social_security_cola,
        benefits_payable = economics.social_security_benefits_payable,
        reduction_year   = economics.social_security_reduction_year )
