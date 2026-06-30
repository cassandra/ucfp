"""Typed in-memory shapes for the Assumptions domain -- the exogenous external factors.

The `Assumptions` aggregate holds what the user must take a forward view on but does not control:
the economic outlook and the tax projection. Both are exogenous engine concepts with no user-facing
reframing, so they *reuse the engine's own types* (`EconomicParameters`, `StatuteProfile`), keeping
the assumptions in lockstep with exactly what the engine projects under (no arbitrary subset, no
silent drift). Independently selectable from a Profile and Plans -- the axis most often varied at
planning time (an Optimistic vs Pessimistic outlook over the same situation and plans).

Economic outlook is seeded from a curated parameter-set library preset (chosen by
`EconomicOutlookVariant`) then user-owned; materialization reads this copy, not the library.
"""
from dataclasses import dataclass
from typing import Optional

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.jurisdiction.law import StatuteProfile


@dataclass( frozen = True )
class Assumptions:
    """One named set of external factors: the editable economic-factors copy (seeded from a preset)
    and the tax forecast. Serialized whole into an `AssumptionsRecord`'s JSON, and materialized
    (with a Profile and Plans) into `ForecastParameters`."""
    economics: Optional[ EconomicParameters ] = None
    statute: Optional[ StatuteProfile ] = None
