"""`ForecastParameters`: the full materialized data a Forecast needs to run N steps.

The N-step analog of `PeriodParameters` -- one container of cohesive sub-objects, in
*materialized* form (the upstream materialization layer builds it from frictionless UX
intent; profiles, ladders, and segment timelines are expanded away by then).

There is no separate "Baseline" input: the opening books are encoded in the asset (and
later liability) parameters' opening values, and the Forecast creates the chart and
ledger from them. A "Scenario" is a *variation* of a ForecastParameters -- the
comparison/what-if layer above the engine -- and is not modelled here.

STUB: subjects, assets, the economic outlook, income streams, expenses, loans, scheduled
events, the frame, filing status, the tax-forecast profile, and the funding knobs (cash
target + draw order, the asset classes drawn from in priority to cover a shortfall).
Auto/feedback events (RMDs) and per-item value-rules and existence windows join later.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.books import Account
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.accounts.handle import Handle
from ucfp.period.events import Purchase, PeriodEvent, Realization, Transfer
from ucfp.period.parameters import DateSpan
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

from .economic_outlook import EconomicOutlook


@dataclass( frozen = True )
class Subject:
    """A person on the forecast -- the invariant kernel (name + birthdate); age is derived
    per interval, and income resolves per subject. `handle` is the planner-minted identity
    that pairs this subject with the accounts they own (required only when the subject owns a
    retirement account, whose owner handle must match). Frozen so a subject can key the
    per-person account map."""

    name      : str
    birthdate : date
    handle    : Optional[ Handle ] = None


@dataclass( frozen = True )
class PropertyAttributes:
    """The tax-relevant facts of a real-estate holding beyond its market value: when it was
    acquired, the depreciable (building) basis -- zero for a residence, the building portion
    for a rental -- and the rental depreciation class. Land is the implicit remainder of the
    asset's opening value. The Forecast turns these into the engine's `TaxProperty`."""

    acquisition_date  : date
    depreciable_basis : Decimal          = Decimal( '0' )
    property_type     : RealPropertyType = RealPropertyType.RESIDENTIAL


@dataclass
class AssetParameters:
    """A holding: its market value at t0 (`opening_value`), its tax basis (`cost_basis`), and
    its asset class. The Forecast seeds the basis as the holding's cost and any embedded gain
    (`opening_value - cost_basis`) as unrealized appreciation -- so a later realization
    recognizes the gain from the true basis, not from t0. A real-estate holding also carries
    `property_attributes` (the tax facts behind §121/§1250); None for any other asset.
    `cost_basis` is required (no defaulting -- an important distinction belongs upstream): a
    retirement account passes 0 (its whole value is taxable/withdrawable on the way out), a
    freshly-valued holding passes `opening_value` (cost = market). `owner_handle` is the
    handle of the subject who owns the holding (matching that `Subject.handle`), required for
    a retirement account -- the owner's age drives the early-withdrawal penalty and RMDs.
    STUB: the value-rule and existence window join later."""

    name                : str
    asset_class         : AssetClass
    opening_value       : Decimal
    cost_basis          : Decimal
    property_attributes : Optional[ PropertyAttributes ] = None
    owner_handle        : Optional[ Handle ]             = None

    def __post_init__( self ):
        """Enforce the retirement-account domain rules: zero cost basis (the engine realizes
        its whole value, so a mis-stated basis -- which would silently under-tax withdrawals
        -- is rejected) and a known owner (whose age drives the penalty and RMDs)."""
        if not self.asset_class.seeds_at_zero_basis:
            return
        if self.cost_basis != 0:
            raise ValueError(
                f'{self.asset_class.label} holdings carry zero tax basis; '
                f'cost_basis must be 0, not {self.cost_basis}.' )
        if self.owner_handle is None:
            raise ValueError(
                f'{self.asset_class.label} holdings require an owner handle (the owner age '
                'drives the early-withdrawal penalty and RMDs).' )
        return


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


@dataclass( frozen = True )
class LoanParameters:
    """A loan owed at the forecast start -- mortgage, car loan, etc. -- specified the way a
    loan naturally is: `opening_balance`, `interest_rate` (annual), and `term` (a Duration,
    e.g. 30 years). The Forecast derives the level payment by amortization at the run's
    granularity, then each interval books interest (= balance x periodic rate) to an
    interest expense account (deductibility per `interest_class`) and reduces the balance by
    principal (= payment - interest) plus `annual_extra_principal`, until paid off. A loan
    payment is principal (debt reduction) plus interest (the only expense), never a single
    'expense'. STUB: existing loans only; a future-originated loan joins later as an Event."""

    name                  : str
    opening_balance       : Decimal
    interest_rate         : Rate
    term                  : Duration
    interest_class        : ExpenseTaxClass = ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST
    annual_extra_principal : Decimal        = Decimal( '0' )


class ScheduledEvent:
    """Base for a user-scheduled money-movement event: it names the holdings it touches and
    the date it occurs, and resolves to a `PeriodEvent` (which holds the accounts) once the
    Forecast has built the books. `to_period_event` receives `holdings` (asset name ->
    holding account) and the cash hub.

    PLACEHOLDER: holdings are referenced by their (run-unique) `name` string. This is the
    deficient stand-in for a stable `Handle` -- the planner-owned, serializable account
    reference that will also key result drill-down; it replaces these names everywhere at
    once when the handle work lands."""

    event_date : date

    def in_span( self, span : DateSpan ) -> bool:
        """Whether this event occurs within the interval `span`."""
        return span.start_date <= self.event_date <= span.end_date

    def to_period_event( self, holdings : dict[ str, Account ], cash : Account ) -> PeriodEvent:
        raise NotImplementedError


@dataclass( frozen = True )
class ScheduledTransfer( ScheduledEvent ):
    """Move `amount` between two named holdings, with no tax effect (e.g. cash -> CD, or a
    rebalance inside a tax-advantaged account)."""

    event_date : date
    source     : str
    target     : str
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], cash : Account ) -> PeriodEvent:
        return Transfer( self.event_date, holdings[ self.source ], holdings[ self.target ], self.amount )


@dataclass( frozen = True )
class ScheduledPurchase( ScheduledEvent ):
    """Acquire `amount` of a named holding at cost, funded from cash. STUB: buys into a
    holding present from t0 (possibly opening at zero value); originating a brand-new
    holding mid-forecast joins later with asset existence windows."""

    event_date : date
    asset      : str
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], cash : Account ) -> PeriodEvent:
        return Purchase( self.event_date, cash, holdings[ self.asset ], self.amount )


@dataclass( frozen = True )
class ScheduledRealization( ScheduledEvent ):
    """Realize `amount` of a named holding -- a sale or pre-tax withdrawal when `destination`
    is None (proceeds to the cash hub), or a conversion when `destination` names another
    holding (e.g. pre-tax -> Roth). Tax treatment follows the source holding's class."""

    event_date  : date
    holding     : str
    amount      : Decimal
    destination : Optional[ str ] = None

    def to_period_event( self, holdings : dict[ str, Account ], cash : Account ) -> PeriodEvent:
        target = cash if self.destination is None else holdings[ self.destination ]
        return Realization( self.event_date, holdings[ self.holding ], self.amount, target )


@dataclass( frozen = True )
class SubsidizedHealthCoverage:
    """Income-subsidized individual-market healthcare coverage over a `window` -- a general
    planning input named for the axis the model cares about (the income-based subsidy that
    couples healthcare cost to the income/tax projection), not for any one program. It is the
    privately-provided, individually-purchased, government-subsidized kind (the US ACA
    marketplace; employer and government-provided coverage are different buckets that need no
    node here -- Medicare's income *surcharge* joins later as a sibling). `household_size` is
    the covered tax-family size; `reference_premium` is the annual premium the subsidy is
    computed against, in today's dollars. The Forecast hands the year's coverage to the tax
    engine, which (US) treats it as ACA enrollment and computes the premium tax credit;
    outside the window the household is uncovered (no subsidy). STUB: constant over the window
    -- a changing household size (survivor transition), premium inflation, and
    enrollment-month proration join later."""

    window            : DateWindow
    household_size    : int
    reference_premium : Decimal

    def covers( self, on_date : date ) -> bool:
        """Whether the household holds this coverage on `on_date`."""
        return self.window.covers( on_date )


@dataclass
class ForecastParameters:
    """The full materialized inputs for an N-step Forecast (see module docstring)."""

    start_date        : date
    end_date          : date
    filing_status     : FilingStatus
    tax_forecast      : TaxForecastProfile
    label             : str                                  = ''
    granularity       : Duration                             = Duration( 1, TimeUnit.YEAR )
    subjects          : list[ Subject ]                      = field( default_factory = list )
    assets            : list[ AssetParameters ]              = field( default_factory = list )
    economic_outlook  : EconomicOutlook                      = field( default_factory = EconomicOutlook )
    income_streams    : list[ IncomeStream ]                 = field( default_factory = list )
    expenses          : list[ ExpenseItem ]                  = field( default_factory = list )
    loans             : list[ LoanParameters ]               = field( default_factory = list )
    events            : list[ ScheduledEvent ]               = field( default_factory = list )
    cash_target       : Decimal                              = Decimal( '0' )
    draw_order        : list[ AssetClass ]                   = field( default_factory = list )
    health_coverage   : Optional[ SubsidizedHealthCoverage ] = None
    initial_tax_state : object                               = None

    def period_spans( self ) -> list[ DateSpan ]:
        """The horizon sliced into consecutive `granularity` intervals (the last truncated
        to `end_date`). Yearly by default; monthly when the granularity is a month."""
        spans  = list()
        cursor = self.start_date
        while cursor <= self.end_date:
            following = self.granularity.add_to( cursor )
            spans.append( DateSpan( cursor, min( following - timedelta( days = 1 ), self.end_date ) ) )
            cursor = following
            continue
        return spans
