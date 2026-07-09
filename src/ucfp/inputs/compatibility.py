"""Whether a `Plans` is consistent with a `Profile`.

Plans reference Profile entities by stable handle (a prepayment names a loan, spending names a
property, retirement timing names a subject, ...) but carry no enforced foreign key -- the two are
independently selected and edited, so a Plans can drift out of step with the Profile it is run
against (the Profile gained or lost an entity the Plans still names). Rather than prevent that
structurally, we check it *at use*: this module resolves every Plans reference against the current
Profile and reports the ones that do not resolve.

It lives here, above `profile` and `plans`, because it depends on both -- neither input subpackage
may depend on the other. Materialization calls `assert_compatible` before composing the engine
parameters; a selection surface can call `compatibility_issues` to flag a stale Plans before a run.

This module also owns the write-side twin, `plans_without_debts`: the same Plans -> Profile debt
references are enumerated once to *report* drift and once to *prune* it when a debt is deleted, so
the two cannot fall out of step.
"""
from dataclasses import replace

from ucfp.inputs.events import CARD_ROLE, LOAN_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import Profile


# The shared lead-in for a plans-drift report, so the raise-at-use error and the pre-run readiness
# check spell the drift the same way.
DRIFT_LEAD_IN = 'These plans reference things your situation no longer has:'


class PlansIncompatibleError( ValueError ):
    """A Plans names Profile entities that do not exist in the Profile it is run against. Carries the
    human-readable `issues` so the run surface can show exactly what to fix."""

    def __init__( self, issues: list[ str ] ):
        self.issues = issues
        super().__init__( DRIFT_LEAD_IN + ' ' + ' '.join( issues ) )


def compatibility_issues( profile: Profile, plans: Plans ) -> list[ str ]:
    """Every Plans reference that does not resolve against `profile`, as user-facing messages -- empty
    when the Plans is fully compatible. The single place that enumerates the Plans -> Profile
    references, so neither materialization nor a selection surface re-spells them."""
    subjects = { subject.handle for subject in profile.subjects }
    accounts = { asset.handle for asset in profile.assets }
    debts    = { debt.handle for debt in profile.debts }
    entities = subjects | accounts | debts | { obligation.handle for obligation in profile.obligations }

    issues = list()
    for timing in plans.timing:
        if timing.subject_handle not in subjects:
            issues.append( f'retirement timing for an unknown person "{timing.subject_handle}";' )
    # Property-expense overrides key by property handle, but a removed property's override is pruned on
    # merge and ignored at materialize, so it needs no drift check here.
    for contribution in plans.contributions:
        if contribution.account_handle not in accounts:
            issues.append(
                f'a contribution to an unknown account "{contribution.account_handle}";' )
    for repayment in plans.loan_repayments:
        if repayment.debt_handle not in debts:
            issues.append( f'a repayment plan for an unknown debt "{repayment.debt_handle}";' )
    for prepayment in plans.prepayments:
        if prepayment.loan_handle not in debts:
            issues.append( f'extra principal on an unknown debt "{prepayment.loan_handle}";' )
    for card_plan in plans.credit_card_plans:
        if card_plan.card_handle not in debts:
            issues.append( f'a paydown plan for an unknown card "{card_plan.card_handle}";' )
    if plans.drawdown is not None:
        for handle, _ in plans.drawdown.sweep_allocation:
            if handle not in accounts:
                issues.append( f'a cash sweep into an unknown account "{handle}";' )
    for event in plans.events:
        for role, handle in event.selections.items():
            if handle not in entities:
                issues.append(
                    f'the event "{event.kind.label}" on an unknown {role} "{handle}";' )
    return issues


def assert_compatible( profile: Profile, plans: Plans ) -> None:
    """Raise `PlansIncompatibleError` if any Plans reference fails to resolve against `profile`."""
    issues = compatibility_issues( profile, plans )
    if issues:
        raise PlansIncompatibleError( issues )


def plans_without_debts( plans: Plans, removed: set ) -> Plans:
    """Every Plans reference to a removed debt handle stripped -- a loan's repayment, its extra
    principal, and its payoff, or a card's paydown plan and its payoff -- so a deleted debt leaves
    nothing dangling. The single place that owns the debt reap, delegated to by every surface that
    deletes a debt."""
    return replace(
        plans,
        loan_repayments   = [ r for r in plans.loan_repayments if r.debt_handle not in removed ],
        prepayments       = [ p for p in plans.prepayments if p.loan_handle not in removed ],
        credit_card_plans = [ c for c in plans.credit_card_plans if c.card_handle not in removed ],
        events            = [ e for e in plans.events if not _reaped_debt_event( e, removed ) ] )


def _reaped_debt_event( event, removed: set ) -> bool:
    """Whether a plan event should be dropped because the debt it targets was removed -- a loan or
    card payoff whose debt is gone."""
    if event.kind is EventKind.LOAN_PAYOFF:
        return event.selections.get( LOAN_ROLE ) in removed
    if event.kind is EventKind.CARD_PAYOFF:
        return event.selections.get( CARD_ROLE ) in removed
    return False
