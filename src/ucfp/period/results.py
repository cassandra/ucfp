"""Outputs of a Period computation."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from uuid import UUID

from common.labeled_enum import LabeledEnum
from ucfp.jurisdiction.engine import TaxState


class NoticeSeverity( LabeledEnum ):
    """How much a Notice should draw the user's attention -- the sort key for importance.
    Two levels: informational (a consequential automatic action that is fine) and a warning
    (an adverse or constraint-straining outcome). Defined low-to-high."""

    INFO    = ( 'Info', 'A consequential automatic action worth surfacing; nothing wrong.' )
    WARNING = ( 'Warning', 'An adverse or constraint-straining outcome the user may need to act on.' )


class NoticeKind( LabeledEnum ):
    """The category of a Notice -- its label is the human title, so the kind alone says what
    happened without reading the linked transaction.

    A Notice is raised only for an outcome that is both unrequested and consequential; a
    requested input (a contribution, a scheduled event) gets a memo, not a Notice. INFO marks
    an automatic consequential action (a forced RMD, a funding draw); WARNING marks an adverse
    or constraint-straining outcome (a penalty, a shortfall, depletion, a capped
    contribution)."""

    FUNDING_DRAW = (
        'Funding Draw', 'Assets were sold to cover a cash shortfall to the target buffer.' )
    PROPERTY_SALE_COSTS = (
        'Property Sale Costs',
        'Selling costs (realtor fee and fixed costs) were charged on a property sale.' )
    REQUIRED_MINIMUM_DISTRIBUTION = (
        'Required Minimum Distribution', 'A pre-tax retirement RMD was forced.' )
    EARLY_WITHDRAWAL_PENALTY = (
        'Early-Withdrawal Penalty', 'A 10% penalty was charged on an early retirement withdrawal.' )
    CONTRIBUTION_CAPPED = (
        'Contribution Capped',
        'A retirement contribution was reduced to its annual limit.' )
    CASH_SHORTFALL = (
        'Cash Shortfall', 'The cash balance went negative -- spending outran available cash.' )
    NET_WORTH_DEPLETED = (
        'Net Worth Depleted', 'Assets no longer cover liabilities; the forecast stops.' )
    APPROXIMATE_TAX_YEAR = (
        'Approximate Tax Year',
        'A partial calendar year (a mid-year start or a non-year-end horizon): its tax is an '
        'estimate or, for a trailing year, unsettled -- the figures are approximate.' )


@dataclass( frozen = True )
class Notice:
    """A notable occurrence raised during a Period -- the planning-insight stream the Forecast
    accumulates and surfaces to the user, distinct from the *input* events: a Notice is what
    actually happened that the user should attend to but did not directly request.

    `kind` is the self-describing category (its label is the title). `severity` ranks
    importance. `amount` is the figure the notice carries (a penalty, an RMD, the shortfall),
    or None. `transaction_uuid` links to the originating transaction (whose `description` memo
    carries the per-posting detail) -- None for a notice about a state rather than a posting."""

    kind             : NoticeKind
    severity         : NoticeSeverity
    amount           : Optional[ Decimal ] = None
    transaction_uuid : Optional[ UUID ]    = None


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
    closing_tax_state : Optional[ TaxState ] = None
