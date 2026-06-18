"""Outputs of a Period computation."""
from dataclasses import dataclass, field


@dataclass( frozen = True )
class Notice:
    """A notable occurrence raised during a Period -- a forced draw, an asset sold,
    savings depleted. This is the planning-insight stream the Forecast accumulates
    and surfaces to the user, distinct from the *input* events: a Notice is what
    actually happened.

    NOTE: a single message for now; a typed kind + structured payload (and a link
    to the realizing transaction) will come as the surfacing layer is built.
    """

    message : str


@dataclass
class PeriodResult:
    """What a Period produces: the notices it raised, whether the stop condition was
    hit, and the engine's closing tax state to thread into the next fiscal year. The
    generated transactions live in the Ledger the Period posted to.

    `closing_tax_state` is the tax engine's updated carryforwards, opaque here (its
    concrete type is the engine's, e.g. the US `TaxState`); None when no engine settled
    this period -- the Forecast carries the prior opening state forward unchanged then."""

    notices           : list[ Notice ] = field( default_factory = list )
    is_depleted       : bool = False
    closing_tax_state : object = None
