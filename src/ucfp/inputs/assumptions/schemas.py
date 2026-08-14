"""Typed in-memory shapes for the Assumptions domain -- the exogenous external factors.

The `Assumptions` aggregate holds what the user must take a forward view on but does not control:
the economic outlook and the tax projection. Both are exogenous engine concepts with no user-facing
reframing, so they *reuse the engine's own types* (`EconomicParameters`, `TaxProjection`), keeping
the assumptions in lockstep with exactly what the engine projects under (no arbitrary subset, no
silent drift). Independently selectable from a Profile and Plans -- the axis most often varied at
planning time (an Optimistic vs Pessimistic outlook over the same situation and plans). The
jurisdiction the tax projection applies to is a Profile fact, not held here, so an Assumptions set
stays jurisdiction-neutral and reusable across profiles.

Economic outlook is seeded from a curated parameter-set library preset (chosen by
`EconomicOutlookVariant`) then user-owned; materialization reads this copy, not the library.
"""
from dataclasses import dataclass
from typing import Optional

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.forecast.parameters import NetWorthCalculation, TransactionCosts
from ucfp.jurisdiction.law import TaxProjection


@dataclass( frozen = True )
class Assumptions:
    """One named set of external factors: the editable economic-factors copy (seeded from a preset),
    the tax projection, the transaction costs applied when an asset is sold, and the net-worth
    calculation (the latent-tax overlay rates). Serialized whole into an `AssumptionsRecord`'s JSON,
    and materialized (with a Profile and Plans) into `ForecastParameters`."""
    economics: Optional[ EconomicParameters ] = None
    tax_projection: Optional[ TaxProjection ] = None
    transaction_costs: Optional[ TransactionCosts ] = None
    net_worth: Optional[ NetWorthCalculation ] = None
