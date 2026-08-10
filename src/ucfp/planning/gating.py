"""Scenario gating for planning features: which of an organization's scenarios are ready to run.

A feature that needs a scenario asks three things -- is there a *complete* one to run, is one blocked
only by *drift* (a Plans->Profile reference the Profile no longer has, clearable in one click), and is
one genuinely *half-built* to resume. Completeness reuses the shared `readiness_issues` bundle check (a
scenario is ready when its resolved Plans + Assumptions, judged against the current Profile and the
records' reviewed sections, raise no issues). Splitting drift out from half-built matters because the two
have different fixes: drift clears with one reconcile, a half-built scenario needs the interview resumed.
"""
from dataclasses import replace

from ucfp.inputs.assumptions.repository import load_assumptions
from ucfp.inputs.plans.repository import load_plans
from ucfp.inputs.profile.repository import load_profile
from ucfp.inputs.scenarios.repository import scenarios_for

from .readiness import readiness_issues


def scenario_readiness( profile_record, scenario_record ) -> list:
    """The readiness issues of a scenario's bundle against `profile_record` -- empty when it is runnable.
    Acknowledgment spans the profile plus the scenario's own Plans and Assumptions, so a step left
    unreviewed during the build keeps the scenario in-progress. A drift issue is routed to *this*
    scenario's one-click reconcile (the record that route needs lives here, not in the bundle-level
    check)."""
    acknowledged = frozenset(
        profile_record.acknowledged_section_keys
        | scenario_record.plans.acknowledged_section_keys
        | scenario_record.assumptions.acknowledged_section_keys )
    issues = readiness_issues(
        load_profile( profile_record ), load_plans( scenario_record.plans ),
        load_assumptions( scenario_record.assumptions ), acknowledged )
    return [ _routed_to_reconcile( issue, scenario_record ) for issue in issues ]


def _routed_to_reconcile( issue, scenario_record ):
    """A drift issue re-pointed at this scenario's one-click "remove stale references" reconcile; any
    other issue is returned unchanged."""
    if not issue.is_drift:
        return issue
    return replace(
        issue, fix_label = 'Remove stale references', fix_route = 'scenario_reconcile',
        fix_route_kwargs = { 'uuid': scenario_record.uuid } )


def scenario_started( scenario_record ) -> bool:
    """Whether the user has actually begun building this scenario -- any Plans or Assumptions step
    reviewed. A Default scenario is auto-created when the Profile is set up, so a never-touched one is
    'in progress' only by construction; this tells it apart from one the user has worked on and would
    recognize resuming."""
    return bool( scenario_record.plans.acknowledged_section_keys
                 or scenario_record.assumptions.acknowledged_section_keys )


def partition_scenarios( organization, profile_record ):
    """The organization's saved scenarios split three ways against the current profile:
    `(complete, drift_blocked, in_progress)`. `complete` are runnable now; `drift_blocked` are runnable
    but for stale Plans->Profile references, each paired with its readiness issues so a surface can show
    what drifted and link the one-click reconcile; `in_progress` are genuinely half-built and resumable.
    A scenario blocked by drift *and* something else is in-progress -- reconcile alone would not run it."""
    complete, drift_blocked, in_progress = list(), list(), list()
    for scenario in scenarios_for( organization ).select_related( 'plans', 'assumptions' ):
        issues = scenario_readiness( profile_record, scenario )
        if not issues:
            complete.append( scenario )
        elif all( issue.is_drift for issue in issues ):
            drift_blocked.append( ( scenario, issues ) )
        else:
            in_progress.append( scenario )
    return complete, drift_blocked, in_progress
