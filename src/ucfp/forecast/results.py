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
    """What a Period produces: the notices it raised and whether the stop condition
    was hit. The generated transactions live in the Ledger the Period posted to."""

    notices     : list = field( default_factory = list )   # list[ Notice ]
    is_depleted : bool = False
