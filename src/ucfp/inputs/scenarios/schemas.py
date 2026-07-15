"""The typed `Scenario` aggregate: a Plans set paired with an Assumptions set.

A scenario is the user's durable unit of "what I plan" -- a named Plans + Assumptions combination. This
dataclass is the *resolved* form: a `ScenarioRecord` references a `PlansRecord` and an `AssumptionsRecord`
(it does not copy them), and `scenarios.repository.load_scenario` materializes their current values into
this pair. A run snapshots the resolved inputs, so a run's provenance against a scenario is derived by
comparing these inputs -- the scenario is never referenced from a run, since its components can change.
"""
from dataclasses import dataclass, field

from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import Plans


@dataclass
class Scenario:
    """One scenario's inputs -- its own Plans and Assumptions. Both default to empty so a fresh scenario
    is constructible before its parts are filled in."""

    plans: Plans = field( default_factory = Plans )
    assumptions: Assumptions = field( default_factory = Assumptions )
