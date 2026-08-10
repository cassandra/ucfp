"""The drift notice a surface shows for a scenario whose Plans reference Profile entities it no longer has.

Every place that surfaces drift -- the Forecast hub, the Scenarios cards, and the Plans flow -- renders
the same thing through the shared `inputs/panes/scenario_drift.html` pane: the individual stale references
and the one-click reconcile that strips them. This is the single builder of that notice, so the surfaces
cannot disagree on what drifted or how to fix it. It lives here (not in `compatibility`, which is pure
Plans<->Profile model logic) because it also resolves a reconcile URL -- a presentation concern.
"""
from django.urls import reverse

from ucfp.inputs.compatibility import compatibility_issues
from ucfp.inputs.plans.repository import load_plans


RECONCILE_LABEL = 'Remove stale references'


def scenario_drift( profile, scenario_record ):
    """The drift notice for a scenario -- `{references, fix_url, fix_label}` for the shared drift pane --
    or None when its plans fully resolve against `profile`. `references` are the individual stale
    references (each `compatibility_issues` string, its trailing `;` trimmed); `fix_url` is the scenario's
    one-click reconcile."""
    references = compatibility_issues( profile, load_plans( scenario_record.plans ) )
    if not references:
        return None
    return {
        'references' : [ reference.rstrip( ' ;' ) for reference in references ],
        'fix_url'    : reverse( 'scenario_reconcile', kwargs = { 'uuid' : scenario_record.uuid } ),
        'fix_label'  : RECONCILE_LABEL }
