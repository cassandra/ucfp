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
from typing import Optional

from ucfp.inputs.plans.schemas import LoanRepayment, LoanTermsSnapshot, Plans
from ucfp.inputs.profile.schemas import LoanTerms, Profile
from ucfp.inputs.expenses import is_renting
from ucfp.inputs.property_expenses import property_handles_for, set_home_rent
from ucfp.inputs.vehicle_expenses import plan_has_content


# The shared lead-in for a plans-drift report, so the raise-at-use error and the pre-run readiness
# check spell the drift the same way.
DRIFT_LEAD_IN = 'These plans reference things your profile no longer has:'


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
    entities   = subjects | accounts | debts
    properties = set( property_handles_for( profile ) )

    issues = list()
    for timing in plans.timing:
        if timing.subject_handle not in subjects:
            issues.append( f'retirement timing for an unknown person "{timing.subject_handle}";' )
    for handle in _stale_property_handles( plans, properties ):
        issues.append( f'a home expense set for an unknown property "{handle}";' )
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
    subjects   = { subject.handle for subject in profile.subjects }
    accounts   = { asset.handle for asset in profile.assets }
    debts      = { debt.handle for debt in profile.debts }
    leased     = { vehicle.handle for vehicle in profile.leased_vehicles }
    properties = set( property_handles_for( profile ) )
    entities   = subjects | accounts | debts

    return replace(
        plans,
        timing            = [ t for t in plans.timing if t.subject_handle in subjects ],
        contributions     = [ c for c in plans.contributions if c.account_handle in accounts ],
        roth_conversions  = [ v for v in plans.roth_conversions if v.source_handle in accounts ],
        withdrawals       = [ w for w in plans.withdrawals if w.source_handle in accounts ],
        loan_repayments   = [ r for r in plans.loan_repayments if r.debt_handle in debts ],
        prepayments       = [ p for p in plans.prepayments if p.loan_handle in debts ],
        loan_terms_snapshots = [ s for s in plans.loan_terms_snapshots if s.debt_handle in debts ],
        credit_card_plans = [ c for c in plans.credit_card_plans if c.card_handle in debts ],
        property_expenses = [ _reconciled_property_expense( e, properties )
                              for e in plans.property_expenses ],
        vehicle_plan      = _reconciled_vehicle_plan( plans.vehicle_plan, accounts, leased ),
        drawdown          = _reconciled_drawdown( plans.drawdown, accounts ),
        events            = [ e for e in plans.events if _event_resolves( e, entities ) ] )


# --- Loan-terms drift (value drift) --------------------------------------
# The existence checks above ask whether a Plans reference still resolves; this asks a *value* question:
# has a debt's Profile contract terms changed since the Plan's repayment was seeded from them? Each
# repayment records a `LoanTermsSnapshot` of the contract at seed time; when the current Profile terms
# diverge from that snapshot, the plan may be built on stale facts. Unlike the existence drift (one
# reconcile that prunes), this offers a *choice* per loan -- reset the repayment to the updated contract,
# or keep the current plan -- since the repayment may legitimately differ from the contract.


def snapshot_of( debt_handle: str, terms: Optional[ LoanTerms ] ) -> LoanTermsSnapshot:
    """A `LoanTermsSnapshot` copying a debt's current Profile `LoanTerms` -- the contract as of now, stored
    on the Plans so a later Profile edit can be noticed. An all-None snapshot for a balance-only loan. The
    single builder, so the seed-time write (in the debt/vehicle plan forms) and the reset/keep refresh
    below produce identical snapshots."""
    if terms is None:
        return LoanTermsSnapshot( debt_handle = debt_handle )
    return LoanTermsSnapshot(
        debt_handle = debt_handle, interest_rate = terms.interest_rate,
        remaining_term = terms.remaining_term, monthly_payment = terms.monthly_payment )


def preserved_snapshot( plans: Plans, debt_handle: str, terms: Optional[ LoanTerms ] ) -> LoanTermsSnapshot:
    """The snapshot to record when (re)writing a debt's repayment: its existing snapshot when it has one --
    the contract as of when the repayment was first established, so a later plan edit does not silently
    accept a since-changed Profile fact -- else a fresh snapshot of the current `terms`. The one seed-time
    write rule, shared by the debt-plan and vehicle-plan forms."""
    existing = next( ( s for s in plans.loan_terms_snapshots if s.debt_handle == debt_handle ), None )
    return existing if existing is not None else snapshot_of( debt_handle, terms )


def loan_terms_drift( profile: Profile, plans: Plans ) -> list:
    """The debt handles whose Profile contract terms (rate/term) have changed since the Plan's repayment
    was seeded from them -- the snapshot no longer matches the current facts, in first-seen order. Empty
    when every snapshot is in step. A snapshot for a debt the Profile no longer has is not reported here
    (that is existence drift, pruned by the reconcile); only value drift on a still-present debt. Payment is
    not compared -- it is re-derived when the balance changes, which is not a change to the contract."""
    terms = { debt.handle: debt.terms for debt in profile.debts }
    drifted = []
    for snapshot in plans.loan_terms_snapshots:
        if snapshot.debt_handle not in terms:
            continue
        current = terms[ snapshot.debt_handle ]
        current_rate = current.interest_rate if current is not None else None
        current_term = current.remaining_term if current is not None else None
        if ( snapshot.interest_rate, snapshot.remaining_term ) != ( current_rate, current_term ):
            drifted.append( snapshot.debt_handle )
    return drifted


def reset_loan_terms( profile: Profile, plans: Plans, debt_handle: str ) -> Plans:
    """Adopt the updated contract for one debt: re-seed its repayment's rate/term from the current Profile
    terms and refresh its snapshot to match, clearing the drift. Extra principal and payoff are untouched.
    When the updated contract is incomplete (missing a rate or term), the repayment is dropped -- an
    incomplete contract cannot seed a loan (matching the forms' non-blocking rule)."""
    terms     = _debt_terms( profile, debt_handle )
    others    = [ r for r in plans.loan_repayments if r.debt_handle != debt_handle ]
    repayment = _repayment_from_terms( debt_handle, terms )
    return replace(
        plans,
        loan_repayments      = others + ( [ repayment ] if repayment is not None else [] ),
        loan_terms_snapshots = _with_snapshot( plans, debt_handle, terms ) )


def keep_loan_terms( profile: Profile, plans: Plans, debt_handle: str ) -> Plans:
    """Keep the current plan for one debt: refresh its snapshot to the current Profile terms without
    touching the repayment, so the drift clears while the plan's own terms stand."""
    return replace(
        plans,
        loan_terms_snapshots = _with_snapshot( plans, debt_handle, _debt_terms( profile, debt_handle ) ) )


def _debt_terms( profile: Profile, debt_handle: str ) -> Optional[ LoanTerms ]:
    debt = next( ( d for d in profile.debts if d.handle == debt_handle ), None )
    return debt.terms if debt is not None else None


def _repayment_from_terms( debt_handle: str, terms: Optional[ LoanTerms ] ) -> Optional[ LoanRepayment ]:
    if terms is None or terms.interest_rate is None or terms.remaining_term is None:
        return None
    return LoanRepayment( debt_handle = debt_handle, interest_rate = terms.interest_rate,
                          remaining_term = terms.remaining_term )


def _with_snapshot( plans: Plans, debt_handle: str, terms: Optional[ LoanTerms ] ) -> list:
    """The snapshots with this debt's refreshed to the given terms (the others untouched)."""
    others = [ s for s in plans.loan_terms_snapshots if s.debt_handle != debt_handle ]
    return others + [ snapshot_of( debt_handle, terms ) ]


# --- Home-rent drift (value drift) ---------------------------------------
# The single-value analog of the loan-terms drift above: one rented home, so no per-item handle.

def home_rent_drift( profile: Profile, plans: Plans ) -> bool:
    """Whether the current Profile rent differs from the value this plan's rented-home rent expense was
    seeded with -- true only while the household rents, a present rent fact exists to reconcile to, and a
    snapshot exists (the rent was seeded). Guarding on `is_renting` keeps switching to own (which clears the
    rent fact) from reading as rent drift; requiring a present fact -- like the loan twin requires present
    terms -- keeps a cleared rent from drifting to a reconcile that would blank the plan's rent."""
    return bool( is_renting( profile )
                 and profile.home_monthly_rent is not None
                 and plans.home_rent_snapshot is not None
                 and profile.home_monthly_rent != plans.home_rent_snapshot )


def reset_home_rent( profile: Profile, plans: Plans ) -> Plans:
    """Adopt the current Profile rent into this plan: set the rent expense's amount and the snapshot to the
    fact, clearing the drift."""
    return set_home_rent( plans, profile.home_monthly_rent )


def keep_home_rent( profile: Profile, plans: Plans ) -> Plans:
    """Keep this plan's rent and refresh the snapshot to the current fact, so the drift clears while the
    plan's own rent stands."""
    return replace( plans, home_rent_snapshot = profile.home_monthly_rent )


def _stale_property_handles( plans: Plans, properties: set ) -> list:
    """The property handles a home-expense override names that are not among the household's current
    properties -- each reported once, in first-seen order. These are a deleted property's per-property
    amounts lingering in the Plans; left in place they would resurrect if the handle were reused."""
    stale = list()
    seen  = set()
    for expense in plans.property_expenses:
        for handle in expense.overrides:
            if ( handle not in properties ) and ( handle not in seen ):
                seen.add( handle )
                stale.append( handle )
    return stale


def _reconciled_property_expense( expense, properties: set ):
    """The property expense with any per-property override for a property the household no longer has
    dropped (the shared Default, not property-keyed, is untouched); the same object when none is stale."""
    kept = { handle: amount for handle, amount in expense.overrides.items() if handle in properties }
    return expense if len( kept ) == len( expense.overrides ) else replace( expense, overrides = kept )


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
