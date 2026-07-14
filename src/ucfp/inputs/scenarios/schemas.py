"""The typed `Scenario` aggregate: a Plans set paired with an Assumptions set.

A scenario is the user's durable unit of "what I plan" -- a named Plans + Assumptions combination, owned
as one **copy** (not links to shared records), so editing it never disturbs anything else and it stays
self-consistent. It is serialized whole into a `ScenarioRecord`'s `data` (see `scenarios.repository`).
A run snapshots the same Plans + Assumptions pair, so a run's provenance against a scenario is derived
by comparing these inputs -- the scenario is never referenced from a run, since it drifts over time.
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
