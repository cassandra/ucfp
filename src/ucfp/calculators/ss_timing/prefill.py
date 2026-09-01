"""Prefill for the Social Security claiming calculator's inputs form.

The form works for anyone, but a signed-in visitor with a saved Profile should not retype what the app
already knows. This resolves the form's initial values, best-effort and read-only:

- People default to each Profile person's birth year and PIA (the primary, then the partner). The
  expected lifetime is always left blank -- it is not a Profile fact yet (deferred to issue #14).
- Assumptions default to the visitor's current scenario's economics, then their most recent saved
  scenario's, then the seeded system defaults.

Anonymous visitors -- and signed-in ones with no profile or scenario -- fall through to blank people and
the system default assumptions. Nothing here writes: the form never changes the saved Profile or scenario.
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

_DEFAULT_SOURCE = 'system defaults'


@dataclass( frozen = True )
class Prefill:
    """The form's resolved starting point: the field `initial` map, whether the people came from a saved
    Profile (`from_profile`, so the page can say so and nudge for the missing lifetimes), and a short
    `assumptions_source` label for where the economic assumptions were drawn from."""

    initial            : dict
    from_profile       : bool
    assumptions_source : str


def build_prefill( request ) -> Prefill:
    """The form's initial values for `request`: the people from a signed-in visitor's Profile (blank for
    anonymous), and the assumptions from their scenario or the system defaults. Best-effort -- any missing
    piece falls back rather than failing, since the calculator must open for anyone."""
    organization        = _organization( request )
    economics, source   = _scenario_economics( request, organization )
    initial             = default_inputs( _assumptions( economics ) )
    people, household, from_profile = _people( _profile( organization ) )
    initial.update( people )
    initial[ 'household' ] = household
    return Prefill( initial = initial, from_profile = from_profile, assumptions_source = source )


def _organization( request ):
    """The signed-in visitor's default organization, or None for an anonymous visitor (or one with no
    membership). Non-creating -- prefill never provisions an organization as a side effect."""
    user = request.user
    if not user.is_authenticated:
        return None
    return OrganizationMember.objects.default_organization_for( user )


def _profile( organization ):
    if organization is None:
        return None
    record = latest_profile( organization )
    return load_profile( record ) if record is not None else None


def _people( profile ) -> tuple[ dict, str, bool ]:
    """The people fields from a Profile: each person's birth year and PIA (the expected lifetime is left
    blank -- not a Profile fact yet), the household kind by whether there is a partner, and whether any
    people were prefilled. Blank people and a couple default when there is no profile."""
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


def _scenario_economics( request, organization ) -> tuple[ object, str ]:
    """The economic parameters to seed the assumptions from, with a source label: the current scenario's,
    else the most recent saved scenario's, else the system defaults. A scenario carrying no economics
    falls through to the defaults too."""
    if organization is None:
        return default_economics(), _DEFAULT_SOURCE
    record = _current_scenario( request, organization ) or latest_scenario( organization )
    if record is not None:
        economics = load_assumptions( record.assumptions ).economics
        if economics is not None:
            return economics, f'your scenario “{record.label}”'
    return default_economics(), _DEFAULT_SOURCE


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
