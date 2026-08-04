"""Scenario gating for planning features: which of an organization's scenarios are ready to run.

A feature that needs a scenario asks two things -- is there a *complete* one to run, and is there a
half-built one to *resume*. Completeness reuses the shared `readiness_issues` bundle check (a scenario is
ready when its resolved Plans + Assumptions, judged against the current Profile and the records' reviewed
sections, raise no issues). Because a scenario is built name-first, an abandoned build persists as an
in-progress scenario, so the split here -- not mere existence -- is what a feature gates on.
"""
from ucfp.inputs.assumptions.repository import load_assumptions
from ucfp.inputs.plans.repository import load_plans
from ucfp.inputs.profile.repository import load_profile
from ucfp.inputs.scenarios.repository import scenarios_for

from .readiness import readiness_issues


def scenario_readiness( profile_record, scenario_record ) -> list:
    """The readiness issues of a scenario's bundle against `profile_record` -- empty when it is runnable.
    Acknowledgment spans the profile plus the scenario's own Plans and Assumptions, so a step left
    unreviewed during the build keeps the scenario in-progress."""
    acknowledged = frozenset(
        profile_record.acknowledged_section_keys
        | scenario_record.plans.acknowledged_section_keys
        | scenario_record.assumptions.acknowledged_section_keys )
    return readiness_issues(
        load_profile( profile_record ), load_plans( scenario_record.plans ),
        load_assumptions( scenario_record.assumptions ), acknowledged )


def scenario_started( scenario_record ) -> bool:
    """Whether the user has actually begun building this scenario -- any Plans or Assumptions step
    reviewed. A Default scenario is auto-created when the Profile is set up, so a never-touched one is
    'in progress' only by construction; this tells it apart from one the user has worked on and would
    recognize resuming."""
    return bool( scenario_record.plans.acknowledged_section_keys
                 or scenario_record.assumptions.acknowledged_section_keys )


def partition_scenarios( organization, profile_record ):
    """The organization's saved scenarios split into (complete, in_progress) against the current profile:
    complete ones are runnable now, in-progress ones are half-built and resumable."""
    complete, in_progress = list(), list()
    for scenario in scenarios_for( organization ).select_related( 'plans', 'assumptions' ):
        target = in_progress if scenario_readiness( profile_record, scenario ) else complete
        target.append( scenario )
    return complete, in_progress
