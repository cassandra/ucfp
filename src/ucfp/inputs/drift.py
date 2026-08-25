"""The drift notice a surface shows for a Plans record that references Profile entities it no longer has.

Every place that surfaces drift -- the Forecast hub, the Scenarios cards, and the Plans flow -- renders
the same thing through the shared `inputs/panes/scenario_drift.html` pane: the individual stale references
and the one-click reconcile that strips them. This is the single builder of that notice, so the surfaces
cannot disagree on what drifted or how to fix it. It is keyed by the *Plans* (which carry the Profile
dependencies), not the scenario, so one notice serves every scenario sharing those Plans. It lives here
(not in `compatibility`, which is pure Plans<->Profile model logic) because it also resolves a reconcile
URL -- a presentation concern.
"""
from typing import Optional

from django.urls import reverse

from ucfp.inputs.compatibility import DRIFT_LEAD_IN, compatibility_issues, loan_terms_drift
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import load_plans
from ucfp.inputs.profile.schemas import Profile


RECONCILE_LABEL = 'Remove stale references'

# The loan-terms (value) drift notice -- the sibling of the existence drift above. Its fix is a per-loan
# choice (update the plan to the new contract, or keep the current plan), so it renders through its own
# pane with two buttons per loan rather than the single reconcile.
LOAN_TERMS_DRIFT_LEAD_IN = "A loan's terms changed in your profile since this plan was set:"
LOAN_TERMS_RESET_LABEL   = 'Update the plan'
LOAN_TERMS_KEEP_LABEL    = 'Keep the current plan'


def plans_drift( profile: Profile, plans_record: PlansRecord ) -> Optional[ dict ]:
    """The drift notice for a Plans record -- `{lead_in, references, fix_url, fix_label}` for the shared
    drift pane -- or None when it fully resolves against `profile`. `lead_in` is the shared `DRIFT_LEAD_IN`
    sentence (so every surface reads the same); `references` are the individual stale references (each
    `compatibility_issues` string, its trailing `;` trimmed); `fix_url` is the Plans' one-click reconcile,
    which fixes every scenario that shares them."""
    references = compatibility_issues( profile, load_plans( plans_record ) )
    if not references:
        return None
    return {
        'lead_in'    : DRIFT_LEAD_IN,
        'references' : [ reference.rstrip( ' ;' ) for reference in references ],
        'fix_url'    : reverse( 'plans_reconcile', kwargs = { 'uuid' : plans_record.uuid } ),
        'fix_label'  : RECONCILE_LABEL }


def plans_loan_terms_drift( profile: Profile, plans_record: PlansRecord ) -> Optional[ dict ]:
    """The loan-terms drift notice for a Plans record -- `{lead_in, loans: [{label, reset_url, keep_url}],
    reset_label, keep_label}` for the shared loan-terms drift pane -- or None when no loan's terms have
    drifted. Each drifted loan carries its debt name and the two per-loan action URLs (update to the current
    contract, or keep the plan). Keyed by the Plans, so one notice serves every scenario sharing them."""
    handles = loan_terms_drift( profile, load_plans( plans_record ) )
    if not handles:
        return None
    names = { debt.handle: debt.name for debt in profile.debts }
    return {
        'lead_in'     : LOAN_TERMS_DRIFT_LEAD_IN,
        'loans'       : [ { 'label'     : names.get( handle, handle ),
                            'reset_url' : reverse( 'plans_loan_terms_reset',
                                                   kwargs = { 'uuid': plans_record.uuid, 'handle': handle } ),
                            'keep_url'  : reverse( 'plans_loan_terms_keep',
                                                   kwargs = { 'uuid': plans_record.uuid, 'handle': handle } ) }
                          for handle in handles ],
        'reset_label' : LOAN_TERMS_RESET_LABEL,
        'keep_label'  : LOAN_TERMS_KEEP_LABEL }
