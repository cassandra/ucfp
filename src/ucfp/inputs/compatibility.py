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
"""
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.plans.schemas import Plans


class PlansIncompatibleError( ValueError ):
    """A Plans names Profile entities that do not exist in the Profile it is run against. Carries the
    human-readable `issues` so the run surface can show exactly what to fix."""

    def __init__( self, issues: list[ str ] ):
        self.issues = issues
        super().__init__(
            'These plans reference things your situation no longer has: ' + ' '.join( issues ) )


def compatibility_issues( profile: Profile, plans: Plans ) -> list[ str ]:
    """Every Plans reference that does not resolve against `profile`, as user-facing messages -- empty
    when the Plans is fully compatible. The single place that enumerates the Plans -> Profile
    references, so neither materialization nor a selection surface re-spells them."""
    subjects = { subject.handle for subject in profile.subjects }
    accounts = { asset.handle for asset in profile.assets }
    loans    = { loan.handle for loan in profile.loans }
    entities = subjects | accounts | loans | { obligation.handle for obligation in profile.obligations }

    issues = list()
    for timing in plans.timing:
        if timing.subject_handle not in subjects:
            issues.append( f'retirement timing for an unknown person "{timing.subject_handle}";' )
    for expense in plans.expenses:
        if expense.property_handle is not None and expense.property_handle not in accounts:
            issues.append(
                f'spending "{expense.name}" on an unknown property "{expense.property_handle}";' )
    for contribution in plans.contributions:
        if contribution.account_handle not in accounts:
            issues.append(
                f'a contribution to an unknown account "{contribution.account_handle}";' )
    for prepayment in plans.prepayments:
        if prepayment.loan_handle not in loans:
            issues.append( f'extra principal on an unknown loan "{prepayment.loan_handle}";' )
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
