"""Outputs of a Period computation."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from uuid import UUID

from common.labeled_enum import LabeledEnum
from ucfp.jurisdiction.engine import TaxState
from ucfp.jurisdiction.tax_worksheet import TaxDisplayWorksheet


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
    PROPERTY_SOLD = (
        'Property Sold',
        'The liquid sources were exhausted, so a whole property in the draw order was sold to cover the '
        'cash shortfall (paying off any mortgage it secured); the indivisible proceeds usually overshoot '
        'and the surplus is swept back into investments.' )
    POSSESSION_SOLD = (
        'Possession Sold',
        'The liquid sources were exhausted, so a whole possession (precious metals or collectibles) in the '
        'draw order was sold to cover the cash shortfall; the indivisible proceeds usually overshoot and '
        'the surplus is swept back into investments.' )
    REQUIRED_MINIMUM_DISTRIBUTION = (
        'Required Minimum Distribution', 'A pre-tax retirement RMD was forced.' )
    EARLY_WITHDRAWAL_PENALTY = (
        'Early-Withdrawal Penalty', 'A 10% penalty was charged on an early retirement withdrawal.' )
    CONTRIBUTION_CAPPED = (
        'Contribution Capped',
        'A retirement contribution was reduced to its annual limit.' )
    SAVINGS_DEPLETED = (
        'Savings Depleted',
        'The funding waterfall drew every available source and cash is still negative -- spending can no '
        'longer be met from sellable assets, so the forecast stops. Net worth is deliberately not the test: '
        'any remaining is illiquid (e.g. a home the household lives in and is not selling), which cannot '
        'fund spending.' )
    PARTIAL_YEAR_UNTAXED = (
        'Untaxed Partial Year',
        'A partial calendar year (a mid-year start, or a horizon short of December 31): tax is '
        'assessed on whole years only, so this year is posted but left untaxed. It carries the '
        'approximate income that escaped tax -- the readily-taxable classes, excluding those '
        '(Social Security, net rental, tax-exempt interest) that need the engine to tax correctly '
        '-- so the user can adjust inputs to compensate.' )


@dataclass( frozen = True )
class Notice:
    """A notable occurrence raised during a Period -- the planning-insight stream the Forecast
    accumulates and surfaces to the user, distinct from the *input* events: a Notice is what
    actually happened that the user should attend to but did not directly request.

    `kind` is the self-describing category (its label is the title). `severity` ranks
    importance. `amount` is the figure the notice carries (a penalty, an RMD, the shortfall),
    or None. `detail` names what `amount` measures when the kind's title does not already say
    (e.g. "in untaxed capital gains") -- None to render the amount bare. `transaction_uuid` links
    to the originating transaction (whose `description` memo carries the per-posting detail) --
    None for a notice about a state rather than a posting."""

    kind             : NoticeKind
    severity         : NoticeSeverity
    amount           : Optional[ Decimal ] = None
    detail           : Optional[ str ]     = None
    transaction_uuid : Optional[ UUID ]    = None


@dataclass
class PeriodResult:
    """What a Period produces: the notices it raised, whether the stop condition was
    hit, and the engine's closing tax state to thread into the next fiscal year. The
    generated transactions live in the Ledger the Period posted to.

    `closing_tax_state` is the tax engine's updated carryforwards, opaque here (its
    concrete type is the engine's, e.g. the US `TaxState`); None when no engine settled
    this period -- the Forecast carries the prior opening state forward unchanged then.

    `property_sales` are the whole-property sales the period effected this interval, each a
    `(holding_handle, sale_date, rent_after)` -- the signal the Forecast reacts to once, to reconfigure the
    property's forward expenses (a residence's own->rent conversion). Whatever triggered the sale (a
    scheduled event or a shortfall drawdown) reports it the same way.

    `tax_worksheet` is the tax display worksheet the engine built for this interval's tax year -- present
    only on the period that settles a tax year (None otherwise), for the run to assemble into the whole
    forecast's worksheet."""

    notices           : list[ Notice ]                  = field( default_factory = list )
    is_depleted       : bool                             = False
    closing_tax_state : Optional[ TaxState ]             = None
    property_sales    : list                             = field( default_factory = list )
    tax_worksheet     : Optional[ TaxDisplayWorksheet ] = None
