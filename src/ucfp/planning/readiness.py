"""Whether the planning inputs are ready to run a forecast -- the shared pre-run gate for every
planning feature.

Two concerns, both keyed to a feature's run controls: `input_availability` reports which of the three
inputs the organization even has (the existence gate, shown before any bundle is chosen), and
`readiness_issues` judges whether a *chosen* Profile + Plans + Assumptions bundle is complete, as
user-facing messages each linked to the input flow that fixes it -- so a feature can stop a doomed run
with actionable guidance instead of surfacing a raw materialization exception.

`readiness_issues` enumerates the issues (reusing `compatibility_issues` for the Plans->Profile drift
it owns), while materialization stays the structural backstop that raises at use. Each issue names the
flow (`fix_route`) that resolves it -- a URL name taking no arguments, so a template can link straight
to it.
"""
from dataclasses import dataclass, field

from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.assumptions.repository import assumptions_for
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.compatibility import DRIFT_LEAD_IN, compatibility_issues
from ucfp.inputs.interview import applicable_sections
from ucfp.inputs.plans.repository import plans_for
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import profiles_for
from ucfp.inputs.profile.schemas import Profile


# The interview step (an `interview_section` key) each field issue routes to, so its link lands on the
# page that resolves it. Drift is not one step -- it keeps a flow-level link.
_FILING_STEP   = 'subjects'
_CLAIMING_STEP = 'income'
_FACTORS_STEP  = 'external-factors'


def input_availability( organization : Organization ) -> dict:
    """Which of the three planning inputs `organization` has at least one of, plus whether all are
    present (`inputs_available`) -- the template context for the existence gate every planning feature
    shows before its run controls. Distinct from `readiness_issues`, which judges a chosen bundle."""
    has_profile     = profiles_for( organization ).exists()
    has_plans       = plans_for( organization ).exists()
    has_assumptions = assumptions_for( organization ).exists()
    return {
        'has_profile'      : has_profile,
        'has_plans'        : has_plans,
        'has_assumptions'  : has_assumptions,
        'inputs_available' : has_profile and has_plans and has_assumptions,
    }


@dataclass( frozen = True )
class ReadinessIssue:
    """One reason a bundle cannot run yet: a user-facing `message` and the input step that resolves it.
    `fix_route` is a URL name and `fix_route_kwargs` its arguments (empty for a flow-entry link, or the
    section key to link straight to one interview step); `fix_label` is the link text. `fix_url` resolves
    the two for a template."""
    message          : str
    fix_label        : str
    fix_route        : str
    fix_route_kwargs : dict = field( default_factory = dict )

    @property
    def fix_url( self ) -> str:
        return reverse( self.fix_route, kwargs = self.fix_route_kwargs )


def readiness_issues(
        profile : Profile, plans : Plans, assumptions : Assumptions,
        acknowledged_sections : frozenset = frozenset() ) -> list[ ReadinessIssue ]:
    """Every reason the bundle is not ready to run, as user-facing issues -- empty when it is ready. The
    single place that enumerates the run's preconditions, so the run surface need not re-spell them and
    materialization's raises stay a backstop. `acknowledged_sections` is the union of the chosen bundle's
    records' seen sections; an unreviewed step gates the run so no section's defaults slip in unseen."""
    return ( _acknowledgment_issues( profile, acknowledged_sections )
             + _profile_issues( profile )
             + _assumptions_issues( assumptions )
             + _plans_issues( profile, plans ) )


def _acknowledgment_issues(
        profile : Profile, acknowledged_sections : frozenset ) -> list[ ReadinessIssue ]:
    """The first applicable interview step (in Profile -> Plans -> Assumptions order) the user has not yet
    seen, linking straight to it to resume the guided flow. Only live (form-backed) steps gate -- a
    declared placeholder is never presented, so it can never be acknowledged."""
    for section in applicable_sections( profile ):
        if section.form is not None and section.key not in acknowledged_sections:
            return [ ReadinessIssue(
                message          = f'"{section.title}" has not been reviewed yet -- continue the '
                                   'interview to finish setup.',
                fix_label        = 'Continue the interview',
                fix_route        = 'interview_section',
                fix_route_kwargs = { 'section' : section.key } ) ]
    return list()


def _profile_issues( profile : Profile ) -> list[ ReadinessIssue ]:
    if profile.filing_status is None:
        return [ ReadinessIssue(
            message          = 'Your situation needs a filing status before a forecast can run.',
            fix_label        = 'Finish your situation',
            fix_route        = 'interview_section',
            fix_route_kwargs = { 'section' : _FILING_STEP } ) ]
    return list()


def _assumptions_issues( assumptions : Assumptions ) -> list[ ReadinessIssue ]:
    if assumptions.economics is None or assumptions.tax_projection is None:
        return [ ReadinessIssue(
            message          = 'These assumptions are missing their external factors (economic outlook '
                               'and tax projection). Open them to finish setup.',
            fix_label        = 'Finish your assumptions',
            fix_route        = 'interview_section',
            fix_route_kwargs = { 'section' : _FACTORS_STEP } ) ]
    return list()


def _plans_issues( profile : Profile, plans : Plans ) -> list[ ReadinessIssue ]:
    """Every plans-side reason a run is blocked: drift against the profile, and any government pension
    left without a claiming date."""
    issues = list()
    drift = compatibility_issues( profile, plans )
    if drift:
        issues.append( ReadinessIssue(
            message   = DRIFT_LEAD_IN + ' ' + ' '.join( drift ),
            fix_label = 'Review your plans',
            fix_route = 'flow_plans' ) )
    issues.extend( _claiming_issues( profile, plans ) )
    return issues


def _claiming_issues( profile : Profile, plans : Plans ) -> list[ ReadinessIssue ]:
    """A claiming-date issue for each government pension entitlement whose subject has no claiming date
    in the plans timing -- the run needs one to place the benefit. Gated on the entitlement existing
    (only present when a benefit was entered), so no benefit means no requirement."""
    claimed = { entry.subject_handle for entry in plans.timing
                if entry.government_pension_claiming_date is not None }
    names   = { subject.handle : subject.name for subject in profile.subjects }
    return [ ReadinessIssue(
        message          = f'Social Security for {names.get( entitlement.subject_handle, "a person" )} '
                           'needs a claiming date.',
        fix_label        = 'Set retirement timing',
        fix_route        = 'interview_section',
        fix_route_kwargs = { 'section' : _CLAIMING_STEP } )
        for entitlement in profile.government_pension
        if entitlement.subject_handle not in claimed ]
