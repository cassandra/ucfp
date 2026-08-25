"""Whether a *chosen* planning bundle is ready to run a forecast -- the shared pre-run gate for every
planning feature.

`readiness_issues` judges whether a selected Profile + Plans + Assumptions bundle is complete, as
user-facing messages each linked to the input flow that fixes it -- so a feature can stop a doomed run
with actionable guidance instead of surfacing a raw materialization exception. It enumerates the
issues (reusing `compatibility_issues` for the Plans->Profile drift it owns), while materialization
stays the structural backstop that raises at use. Each issue carries a `fix_route` (URL name) and
`fix_route_kwargs`, resolved through `fix_url`, so a template can link straight to the step that
resolves it.

The prior existence gate -- whether the organization has each input at all -- now lives in
`inputs.state` (`InputState`), one step earlier than the bundle completeness judged here.
"""
from dataclasses import dataclass, field

from django.urls import reverse

from ucfp.inputs.compatibility import DRIFT_LEAD_IN, compatibility_issues, loan_terms_drift
from ucfp.inputs.interview import applicable_sections
from ucfp.inputs.plans.repository import load_plans
from ucfp.inputs.profile.repository import load_profile
from ucfp.inputs.state import (
    assumptions_completion_blockers, plans_completion_blockers, profile_completion_blockers )


@dataclass( frozen = True )
class ReadinessIssue:
    """One reason a bundle cannot run yet: a user-facing `message` and the input step that resolves it.
    `fix_route` is a URL name and `fix_route_kwargs` its arguments (empty for a flow-entry link, or the
    section key to link straight to one interview step); `fix_label` is the link text. `fix_url` resolves
    the two for a template. `is_drift` marks a Plans->Profile drift issue -- the one kind a scenario can
    clear in one click (a reconcile), so a selection surface can bucket it distinctly and render the
    stale references and reconcile through the shared `inputs.drift` notice. `is_loan_terms_drift` marks
    the sibling *value* drift (a loan's contract terms changed since the plan seeded from them); it buckets
    the same way (runnable once resolved, no interview resume), but its fix is a per-loan reset/keep choice
    rather than the one-click reconcile."""
    message             : str
    fix_label           : str
    fix_route           : str
    fix_route_kwargs    : dict  = field( default_factory = dict )
    is_drift            : bool  = False
    is_loan_terms_drift : bool  = False

    @property
    def is_reconcilable_drift( self ) -> bool:
        """Whether this issue is a Plans->Profile drift a surface resolves in place (existence or loan-term)
        rather than by resuming the interview -- so gating can bucket it as drift-blocked."""
        return self.is_drift or self.is_loan_terms_drift

    @property
    def fix_url( self ) -> str:
        return reverse( self.fix_route, kwargs = self.fix_route_kwargs )


def readiness_issues( profile_record, plans_record, assumptions_record ) -> list[ ReadinessIssue ]:
    """Every reason the bundle is not ready to run, as user-facing issues -- empty when it is ready. The
    single place that enumerates the run's preconditions, and it *delegates*: the per-input completeness
    lives once in `inputs.state`, so this reads whether each of the Profile, Plans, and Assumptions is
    complete against the current profile and turns their blockers into flow-linked run issues. It adds only
    the two genuinely cross-input concerns -- an unreviewed step (State 0), and Plans->Profile drift.
    Materialization stays the structural backstop that raises at use."""
    profile = load_profile( profile_record )
    plans   = load_plans( plans_record )
    return ( _not_finished_issues( profile, profile_record, plans_record, assumptions_record )
             + _blocker_issues( profile_completion_blockers( profile_record ), 'flow_profile' )
             + _blocker_issues( plans_completion_blockers( profile, plans_record ), 'flow_plans' )
             + _blocker_issues( assumptions_completion_blockers( profile, assumptions_record ), 'flow_assumptions' )
             + _drift_issues( profile, plans )
             + _loan_terms_drift_issues( profile, plans ) )


# The per-input flow each blocker links to, and its resume-link label -- a blocker is a whole-input concern
# (the interview stepper points to the exact step within), so it links to the input's flow, not one step.
_FLOW_LABELS = {
    'flow_profile'     : 'Finish your situation',
    'flow_plans'       : 'Finish your plan',
    'flow_assumptions' : 'Finish your assumptions',
}


def _blocker_issues( blockers : list, flow_route : str ) -> list[ ReadinessIssue ]:
    """Each per-input completion blocker (from `inputs.state`) as a run issue linked to that input's flow."""
    return [ ReadinessIssue( message = message, fix_label = _FLOW_LABELS[ flow_route ], fix_route = flow_route )
             for message in blockers ]


def _not_finished_issues(
        profile, profile_record, plans_record, assumptions_record ) -> list[ ReadinessIssue ]:
    """The first applicable interview step (in Profile -> Plans -> Assumptions order) the user has not yet
    seen -- State 0, linking straight to it to resume the guided flow. Only live (form-backed) steps gate."""
    acknowledged = frozenset(
        profile_record.acknowledged_section_keys
        | plans_record.acknowledged_section_keys
        | assumptions_record.acknowledged_section_keys )
    for section in applicable_sections( profile ):
        if section.form is not None and section.key not in acknowledged:
            return [ ReadinessIssue(
                message          = f'"{section.title}" has not been reviewed yet -- continue the '
                                   'interview to finish setup.',
                fix_label        = 'Continue the interview',
                fix_route        = 'interview_section',
                fix_route_kwargs = { 'section' : section.key } ) ]
    return list()


def _drift_issues( profile, plans ) -> list[ ReadinessIssue ]:
    """Plans->Profile drift (stale references) as one issue -- the cross-input concern this gate owns.
    `is_drift` lets a selection surface bucket it distinctly (the reconcilable kind, cleared in one click)
    and render the stale references + fix through the shared `inputs.drift` notice."""
    drift = compatibility_issues( profile, plans )
    if not drift:
        return list()
    return [ ReadinessIssue(
        message   = DRIFT_LEAD_IN + ' ' + ' '.join( drift ),
        fix_label = 'Review your plans',
        fix_route = 'flow_plans',
        is_drift  = True ) ]


def _loan_terms_drift_issues( profile, plans ) -> list[ ReadinessIssue ]:
    """Loan-term *value* drift (a debt's Profile contract terms changed since the plan seeded from them) as
    one issue -- the plan may be built on stale terms, so the run waits on an explicit reset/keep choice.
    `is_loan_terms_drift` buckets it as drift-blocked (runnable once resolved) while marking that its fix is
    the per-loan reset/keep notice, not the one-click reconcile."""
    if not loan_terms_drift( profile, plans ):
        return list()
    return [ ReadinessIssue(
        message   = "A loan's terms changed in your profile since this plan was set -- choose whether to "
                    'update the plan or keep it.',
        fix_label = 'Review your plans',
        fix_route = 'flow_plans',
        is_loan_terms_drift = True ) ]
