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

This module also owns the write-side twin, `plans_reconciled_with_profile`: the same Plans -> Profile
references are enumerated once to *report* drift (`compatibility_issues`) and once to *prune* it, so
the two cannot fall out of step. That reconcile is the single on-demand cleanup a run surface offers
for a drifted scenario; a Profile edit does not prune Plans eagerly.
"""
from dataclasses import replace
from decimal import Decimal

from ucfp.inputs.events import CARD_ROLE, LOAN_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.vehicle_expenses import plan_has_content


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
    entities = subjects | accounts | debts

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
    for conversion in plans.roth_conversions:
        if conversion.source_handle not in accounts:
            issues.append(
                f'a Roth conversion from an unknown account "{conversion.source_handle}";' )
    for withdrawal in plans.withdrawals:
        if withdrawal.source_handle not in accounts:
            issues.append(
                f'a withdrawal from an unknown account "{withdrawal.source_handle}";' )
    for repayment in plans.loan_repayments:
        if repayment.debt_handle not in debts:
            issues.append( f'a repayment plan for an unknown debt "{repayment.debt_handle}";' )
    for prepayment in plans.prepayments:
        if prepayment.loan_handle not in debts:
            issues.append( f'extra principal on an unknown debt "{prepayment.loan_handle}";' )
    for card_plan in plans.credit_card_plans:
        if card_plan.card_handle not in debts:
            issues.append( f'a paydown plan for an unknown card "{card_plan.card_handle}";' )
    leased = { vehicle.handle for vehicle in profile.leased_vehicles }
    if plans.vehicle_plan is not None:
        for disposition in plans.vehicle_plan.dispositions:
            if disposition.vehicle_handle not in accounts:
                issues.append(
                    f'a plan for an unknown vehicle "{disposition.vehicle_handle}";' )
        for disposition in plans.vehicle_plan.leased_dispositions:
            if disposition.vehicle_handle not in leased:
                issues.append(
                    f'a plan for an unknown leased vehicle "{disposition.vehicle_handle}";' )
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


def plans_reconciled_with_profile( profile: Profile, plans: Plans ) -> Plans:
    """`plans` with every reference that does not resolve against `profile` pruned, so the result is
    compatible (`compatibility_issues` returns nothing for it). The write-side twin of
    `compatibility_issues`, mirroring it category for category so report and prune stay in step. This is
    the single on-demand cleanup a run surface offers to reconcile a drifted scenario -- where a stale
    reference in any scenario is resolved, since a Profile edit no longer prunes Plans eagerly."""
    subjects = { subject.handle for subject in profile.subjects }
    accounts = { asset.handle for asset in profile.assets }
    debts    = { debt.handle for debt in profile.debts }
    leased   = { vehicle.handle for vehicle in profile.leased_vehicles }
    entities = subjects | accounts | debts

    return replace(
        plans,
        timing            = [ t for t in plans.timing if t.subject_handle in subjects ],
        contributions     = [ c for c in plans.contributions if c.account_handle in accounts ],
        roth_conversions  = [ v for v in plans.roth_conversions if v.source_handle in accounts ],
        withdrawals       = [ w for w in plans.withdrawals if w.source_handle in accounts ],
        loan_repayments   = [ r for r in plans.loan_repayments if r.debt_handle in debts ],
        prepayments       = [ p for p in plans.prepayments if p.loan_handle in debts ],
        credit_card_plans = [ c for c in plans.credit_card_plans if c.card_handle in debts ],
        vehicle_plan      = _reconciled_vehicle_plan( plans.vehicle_plan, accounts, leased ),
        drawdown          = _reconciled_drawdown( plans.drawdown, accounts ),
        events            = [ e for e in plans.events if _event_resolves( e, entities ) ] )


def _reconciled_vehicle_plan( plan, accounts: set, leased: set ):
    """The vehicle plan with dispositions for a missing owned or leased vehicle dropped, collapsing an
    emptied plan back to None (as every form `apply` does, so a plan reads as 'started' only while it
    still holds something). None passes through unchanged."""
    if plan is None:
        return None
    reaped = replace(
        plan,
        dispositions        = [ d for d in plan.dispositions if d.vehicle_handle in accounts ],
        leased_dispositions = [ d for d in plan.leased_dispositions if d.vehicle_handle in leased ] )
    return reaped if plan_has_content( reaped ) else None


def _reconciled_drawdown( drawdown, accounts: set ):
    """The drawdown with any cash-sweep weight on a missing account dropped and the survivors
    renormalized so their weights still sum to 1 (the allocation stays valid); an all-dropped sweep
    leaves no sweep. None, or a sweep with nothing dropped, passes through unchanged."""
    if drawdown is None:
        return None
    kept = [ ( handle, weight ) for handle, weight in drawdown.sweep_allocation if handle in accounts ]
    if len( kept ) == len( drawdown.sweep_allocation ):
        return drawdown
    return replace( drawdown, sweep_allocation = _renormalized_weights( kept ) )


def _renormalized_weights( weights: list ) -> list:
    """`(handle, weight)` pairs rescaled to sum to exactly 1 -- the last pair carries the rounding
    residue so the total is exact -- or an empty list when there are none."""
    total = sum( ( weight for _handle, weight in weights ), Decimal( '0' ) )
    if not weights or total == 0:
        return list()
    scaled  = [ ( handle, weight / total ) for handle, weight in weights ]
    residue = Decimal( '1' ) - sum( ( weight for _handle, weight in scaled ), Decimal( '0' ) )
    handle, last = scaled[ -1 ]
    return scaled[ :-1 ] + [ ( handle, last + residue ) ]


def _event_resolves( event, entities: set ) -> bool:
    """Whether every entity a plan event selects still exists -- an event is dropped whole when any role
    it names (a subject, an account, a debt) is gone, matching how the drift check flags it."""
    return all( handle in entities for handle in event.selections.values() )


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


def plans_without_vehicles( plans: Plans, removed: set ) -> Plans:
    """Every vehicle-plan disposition for a removed vehicle handle stripped -- an owned disposition or a
    leased one -- so a deleted current vehicle leaves no dangling plan. The vehicle counterpart of
    `plans_without_debts`, called when a vehicle (owned or leased) is deleted from the Profile. (Owned and
    leased handles are disjoint, so filtering both lists by the same removed set reaps each correctly. Net-
    new plan vehicles and running costs are not keyed to a Profile vehicle, so they are untouched.)"""
    plan = plans.vehicle_plan
    if plan is None:
        return plans
    owned  = [ d for d in plan.dispositions if d.vehicle_handle not in removed ]
    leased = [ d for d in plan.leased_dispositions if d.vehicle_handle not in removed ]
    reaped = replace( plan, dispositions = owned, leased_dispositions = leased )
    # Collapse an emptied plan back to None, as every form `apply` does, so reaping a vehicle's only
    # disposition never leaves a spurious plan that reads as "started".
    return replace( plans, vehicle_plan = reaped if plan_has_content( reaped ) else None )


def plans_without_accounts( plans: Plans, removed: set ) -> Plans:
    """Every Plans reference to a removed account handle stripped -- a contribution into it, and a Roth
    conversion or scheduled withdrawal from it -- so a removed retirement account (a departed subject's)
    leaves no dangling plan. The account counterpart of `plans_without_debts`, called when a subject is
    dropped. (Events and the sweep also name accounts; those are left to the drift check, since they target
    the shared taxable accounts rather than a departed subject's retirement ones.)"""
    return replace(
        plans,
        contributions    = [ c for c in plans.contributions if c.account_handle not in removed ],
        roth_conversions = [ v for v in plans.roth_conversions if v.source_handle not in removed ],
        withdrawals      = [ w for w in plans.withdrawals if w.source_handle not in removed ] )
