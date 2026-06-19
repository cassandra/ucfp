"""`ForecastParameters`: the full materialized data a Forecast needs to run N steps.

The N-step analog of `PeriodParameters` -- one container of cohesive sub-objects, in
*materialized* form (the upstream materialization layer builds it from frictionless UX
intent; profiles, ladders, and segment timelines are expanded away by then).

There is no separate "Baseline" input: the opening books are encoded in the asset (and
later liability) parameters' opening values, and the Forecast creates the chart and
ledger from them. A "Scenario" is a *variation* of a ForecastParameters -- the
comparison/what-if layer above the engine -- and is not modelled here.

STUB: subjects, assets, the economic outlook, income streams, expenses, the frame, filing
status, the tax-forecast profile, and the cash-target knob. Liabilities and Events join
incrementally; per-item value-rules and existence windows ride on the item sub-objects.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from common.date_window import DateWindow
from common.recurrence import Recurrence
from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.period.parameters import DateSpan
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

from .economic_outlook import EconomicOutlook


def _add_years( anchor : date, years : int ) -> date:
    """`anchor` advanced by whole years (Feb 29 -> Feb 28 in a non-leap target year)."""
    try:
        return anchor.replace( year = anchor.year + years )
    except ValueError:
        return anchor.replace( year = anchor.year + years, day = 28 )


@dataclass( frozen = True )
class Subject:
    """A person on the forecast -- the invariant kernel (name + birthdate); age is derived
    per interval, and income resolves per subject. Frozen so a subject can key the
    per-person account map."""

    name      : str
    birthdate : date


@dataclass
class AssetParameters:
    """A holding: its opening value and asset class. The Forecast creates the holding
    account from this and seeds the opening value. STUB: `opening_value` is the basis
    (= market at t0, no embedded unrealized gain); a basis/market split and the
    value-rule + existence window join later."""

    name          : str
    asset_class   : AssetClass
    opening_value : Decimal


@dataclass( frozen = True )
class IncomeStream:
    """A recurring received income for one subject over an existence `window` -- wages, a
    pension (`ORDINARY`), Social Security, or gross rental. `annual_amount` is gross in
    forecast-start ("today's") dollars; the Forecast grows it to nominal by the income
    class's rate (the COLA lives in the Economic Outlook, per class) and gates it to the
    window. Interest/dividends/gains come from assets, and IRA/401(k) withdrawals are asset
    draws, so none of those are streams."""

    subject          : Subject
    income_tax_class : IncomeTaxClass
    annual_amount    : Decimal
    window           : DateWindow = DateWindow()


@dataclass( frozen = True )
class WindowedAmount:
    """A monetary amount (today's dollars) in effect over a `window` -- the segment type
    for an expense's amount `Schedule` (e.g. one lifestyle level over a span)."""

    amount : Decimal
    window : DateWindow = DateWindow()


@dataclass( frozen = True )
class ExpenseItem:
    """A recurring expense -- one chart line. `amounts` is the per-occurrence cost over
    time (today's dollars, stepping with lifestyle); `recurrence` places the occurrences;
    `window` is the item's existence. The Forecast posts, per interval, the occurrences in
    that interval x the amount then in effect, inflated -- to a per-item account tagged with
    `expense_tax_class`, so the Books keep item detail while tax aggregates by class."""

    name              : str
    expense_tax_class : ExpenseTaxClass
    amounts           : Schedule[ WindowedAmount ]
    recurrence        : Recurrence
    window            : DateWindow = DateWindow()


@dataclass
class ForecastParameters:
    """The full materialized inputs for an N-step Forecast (see module docstring)."""

    start_date        : date
    end_date          : date
    filing_status     : FilingStatus
    tax_forecast      : TaxForecastProfile
    label             : str                     = ''
    subjects          : list[ Subject ]         = field( default_factory = list )
    assets            : list[ AssetParameters ] = field( default_factory = list )
    economic_outlook  : EconomicOutlook         = field( default_factory = EconomicOutlook )
    income_streams    : list[ IncomeStream ]    = field( default_factory = list )
    expenses          : list[ ExpenseItem ]     = field( default_factory = list )
    cash_target       : Decimal                 = Decimal( '0' )
    initial_tax_state : object                  = None

    def period_spans( self ) -> list[ DateSpan ]:
        """The horizon sliced into consecutive one-year intervals (the last truncated to
        `end_date`). Granularity is yearly for now -- it matches the annual tax engine."""
        spans  = list()
        cursor = self.start_date
        while cursor <= self.end_date:
            following = _add_years( cursor, 1 )
            spans.append( DateSpan( cursor, min( following - timedelta( days = 1 ), self.end_date ) ) )
            cursor = following
            continue
        return spans
