"""`ForecastParameters`: the full materialized data a Forecast needs to run N steps.

The N-step analog of `PeriodParameters` -- one container of cohesive sub-objects, in
*materialized* form (the upstream materialization layer builds it from frictionless UX
intent; profiles, ladders, and segment timelines are expanded away by then).

There is no separate "Baseline" input: the opening books are encoded in the asset (and
later liability) parameters' opening values, and the Forecast creates the chart and
ledger from them. A "Scenario" is a *variation* of a ForecastParameters -- the
comparison/what-if layer above the engine -- and is not modelled here.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.date_span import DateSpan
from common.date_window import DateWindow
from common.labeled_enum import LabeledEnum
from common.rate import Rate, ZERO_RATE
from common.recurrence import Cadence, Duration, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.books import Account
from ucfp.accounts.chart import Chart
from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    RealPropertyType,
    SystemAccountRole,
)
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.schemas import Handle
from ucfp.period.events import (
    ExternalDisbursement, ExternalReceipt, LoanPayoff, PeriodEvent, PropertySale, Purchase,
    Realization, Transfer )
from ucfp.period.parameters import PropertyData
from ucfp.jurisdiction.engine import TaxState
from ucfp.jurisdiction.law import StatuteProfile
from ucfp.jurisdiction.enums import FilingStatus

from .economic_outlook import EconomicOutlook


@dataclass( frozen = True )
class TransactionCosts:
    """The household's assumed one-time costs of selling an asset. Today it holds a property sale's
    realtor commission (a flat rate on the sale price) and fixed costs (title/escrow/transfer, given in
    forecast-start dollars and inflation-adjusted to the sale year). Field names are event-qualified so
    further transaction costs can join without ambiguity."""
    property_sale_realtor_fee_rate : Rate    = ZERO_RATE
    property_sale_fixed_cost       : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class NetWorthCalculation:
    """The household's assumptions for adjusting reported net worth toward realizable wealth. Today it
    holds the two rates the Estimated Future Taxes overlay applies to latent tax -- the ordinary rate on
    pre-tax retirement balances and the capital-gains rate on unrealized investment gains. Both default
    to zero, which books no overlay (net worth stays gross). Named for the calculation, not the tax, so
    other net-worth adjustments can join without renaming the section."""
    ordinary_tax_rate      : Rate = ZERO_RATE
    capital_gains_tax_rate : Rate = ZERO_RATE


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
    asset's opening value. The Forecast turns these into the engine's `TaxProperty`.

    For a rental, the asset's `cost_basis` must be the ORIGINAL purchase price, not the
    depreciated/adjusted basis: the book gain at sale is proceeds - cost_basis (the
    appreciation, recognized as a long-term gain), and the engine adds the accumulated
    depreciation back on top as §1250 recapture (taxed at up to 25%). Passing the adjusted
    basis would double-count the depreciation."""

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
    freshly-valued holding passes `opening_value` (cost = market). `handle` is the planner's
    stable identity for this holding's account (distinct from the display `name`), needed for a
    scheduled event to reference it or for result drill-down; None for a holding neither
    references. `owner_handle` is the handle of the *subject* who owns it (matching that
    `Subject.handle`), required for a retirement account -- the owner's age drives the
    early-withdrawal penalty and RMDs."""

    name                : str
    asset_class         : AssetClass
    opening_value       : Decimal
    cost_basis          : Decimal
    handle              : Optional[ Handle ]             = None
    property_attributes : Optional[ PropertyAttributes ] = None
    owner_handle        : Optional[ Handle ]             = None

    def __post_init__( self ) -> None:
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
class WindowedAmount:
    """A monetary amount (today's dollars) in effect over a `window` -- the segment type for a
    flow's amount `Schedule` (e.g. one income or lifestyle level over a span)."""

    amount : Decimal
    window : DateWindow = DateWindow()


@dataclass( frozen = True )
class IncomeStream:
    """A smooth received income for one subject over an existence `window` -- wages, a pension
    (`ORDINARY`), Social Security, or gross rental -- the rate counterpart of `ExpenseStream`.
    `amounts` is the gross level in forecast-start ("today's") dollars, stepping over time with
    life stage; the Forecast grows it to nominal by the income class's rate (the COLA lives in
    the Economic Outlook, per class), prorates it evenly across each interval, and gates it to
    the window. Interest/dividends/gains come from assets, and IRA/401(k) withdrawals are asset
    draws, so none of those are streams. `source_handle` is the holding this income is sourced from
    (a rental property), carried so per-property rental tax can key on it; None otherwise."""

    subject          : Optional[ Subject ]
    income_tax_class : IncomeTaxClass
    amounts          : Schedule[ WindowedAmount ]
    window           : DateWindow         = DateWindow()
    source_handle    : Optional[ Handle ] = None
    name             : Optional[ str ]    = None   # the source's own label, for the posting memo


@dataclass( frozen = True )
class IncomeItem:
    """Received income for one subject with a real cadence -- the income counterpart of
    `ExpenseItem`. `amounts` is the per-occurrence gross over time (today's dollars, stepping
    with life stage); `cadence` places the occurrences (a `Recurrence` for income known per
    period -- "$5,000/month" -- or a `OneTime` for a single dated receipt such as a bonus or
    settlement); `window` is the item's existence. The Forecast posts, per interval, the
    occurrences in that interval x the amount then in effect, grown to nominal by the income
    class's rate, to the per-(subject, class) revenue account (shared with any `IncomeStream`
    of the same subject and class). For smooth income with no meaningful schedule, use
    `IncomeStream` instead. `source_handle` is the holding this income is sourced from (a rental
    property), carried so per-property rental tax can key on it; None otherwise."""

    subject          : Optional[ Subject ]
    income_tax_class : IncomeTaxClass
    amounts          : Schedule[ WindowedAmount ]
    cadence          : Cadence
    window           : DateWindow         = DateWindow()
    source_handle    : Optional[ Handle ] = None
    name             : Optional[ str ]    = None   # the source's own label, for the posting memo


@dataclass( frozen = True )
class ExpenseItem:
    """An expense with a real cadence -- one chart line. `amounts` is the per-occurrence cost
    over time (today's dollars, stepping with lifestyle); `cadence` places the occurrences (a
    `Recurrence` for a repeating cost, a `OneTime` for a single dated one); `window` is the
    item's existence. The Forecast posts, per interval, the occurrences in that interval x the
    amount then in effect, inflated -- to a per-item account tagged with `expense_tax_class`, so
    the Books keep item detail while tax aggregates by class. `handle` is the planner's identity
    for the item's account, to associate it with the planner's artifact in results; optional.
    For a smooth cost with no meaningful schedule, use `ExpenseStream` instead.

    `cadence_anchor` phases the recurrence independently of the `window`: by default the cadence is
    anchored to the window's own start, but a cost whose schedule outlives any single window -- a
    fleet-wide vehicle running cost that carries across a car's replacements -- anchors to a shared
    origin so the phase stays continuous, and the window merely gates which occurrences apply.
    Without it, two adjacent windows (a car and its replacement) would each restart the cadence and
    double-count the changeover period."""

    name              : str
    expense_tax_class : ExpenseTaxClass
    amounts           : Schedule[ WindowedAmount ]
    cadence           : Cadence
    window            : DateWindow      = DateWindow()
    handle            : Optional[ Handle ] = None
    cadence_anchor    : Optional[ date ] = None


@dataclass( frozen = True )
class ExpenseStream:
    """A smooth recurring expense with no meaningful sub-annual schedule -- living costs, an
    annual vacation -- the expense counterpart of `IncomeStream`. `amounts` is the cost level in
    forecast-start ("today's") dollars, stepping over time with lifestyle; the Forecast inflates
    it by the class rate and *prorates* it evenly across each interval (as it does income), so the
    resolved figure is the same at any granularity. Use `ExpenseItem` instead for a cost with a
    real cadence -- a monthly utility, an annual property-tax bill, a car every N years -- whose
    timing within the year is meaningful and should fall in one period. Smoothing is an
    approximation valid only while the granularity stays coarse relative to the real cadence (we
    cap at monthly); it would misrepresent a true schedule at finer resolution. `handle` is the
    planner's identity for the item's account; optional."""

    name              : str
    expense_tax_class : ExpenseTaxClass
    amounts           : Schedule[ WindowedAmount ]
    window            : DateWindow         = DateWindow()
    handle            : Optional[ Handle ] = None


@dataclass( frozen = True )
class LoanParameters:
    """A loan owed at the forecast start -- mortgage, car loan, etc. -- specified the way a
    loan naturally is: `opening_balance`, `interest_rate` (annual), and `term` (a Duration,
    e.g. 30 years). The Forecast derives the level payment by amortization at the run's
    granularity, then each interval books interest (= balance x periodic rate) to an
    interest expense account (deductibility per `interest_class`) and reduces the balance by
    principal (= payment - interest) plus `annual_extra_principal`, until paid off. A loan
    payment is principal (debt reduction) plus interest (the only expense), never a single
    'expense'. A loan creates two accounts -- the liability and an interest expense -- so it
    carries two planner handles (`handle`, `interest_handle`) to associate each with the
    planner's loan artifact when presenting results; both optional.

    A loan is present from t0 with its `opening_balance` seeded into the books, unless
    `origination_date` is set: then it originates mid-forecast, its `opening_balance` (the
    principal borrowed) credited to the liability with the proceeds landing in cash on that date,
    and amortization beginning from there -- the recurring-financing counterpart of the t0 loan.
    The level payment is derived from the principal and term either way (the term length, not the
    start date, sets it), so an originated loan amortizes over its term from origination."""

    name                  : str
    opening_balance       : Decimal
    interest_rate         : Rate
    term                  : Duration
    interest_class        : ExpenseTaxClass  = ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST
    annual_extra_principal : Decimal         = Decimal( '0' )
    handle                : Optional[ Handle ] = None
    interest_handle       : Optional[ Handle ] = None
    origination_date      : Optional[ date ]   = None


class ContributionSource( LabeledEnum ):
    """Where a retirement contribution comes from -- which sets its money source and tax
    treatment. WAGE (payroll 401(k) deferral) and PERSONAL (direct IRA) both come from cash
    and are deductible into a pre-tax account; they differ only in which annual limit they count
    against -- the employer-plan (elective-deferral) limit versus the personal (IRA) limit.
    EMPLOYER (match) is the employer's money -- external, never deductible, taxed only on
    withdrawal, and counted against neither employee limit."""

    WAGE     = ( 'Wage Deferral', 'Payroll 401(k)/403(b) deferral from the employee.' )
    PERSONAL = ( 'Personal', 'A direct personal contribution (e.g. a traditional or Roth IRA).' )
    EMPLOYER = ( 'Employer Match', 'An employer contribution; external money, taxed on withdrawal.' )


@dataclass( frozen = True )
class RetirementContribution:
    """A recurring contribution into a retirement holding over a `window` -- the accrual-phase
    mirror of a withdrawal. `account` is the target holding's handle; its asset class (pre-tax
    vs Roth) and owner come from that holding, so they are not restated here. `amount` is the
    annual contribution in today's dollars, grown by wage growth. `source` sets the money
    source and deductibility (see `ContributionSource`): a cash contribution to a pre-tax
    holding is deducted above the line; a Roth contribution and an employer match are not. The
    annual contribution limit is enforced (rejected at build if the first year is over, clamped
    with a Notice if a later year grows past it). The IRA/Roth income phase-outs are not
    enforced: the planner states an amount within the limit and the engine trusts it."""

    account : Handle
    amount  : Decimal
    source  : ContributionSource
    window  : DateWindow = DateWindow()


@dataclass( frozen = True )
class RecurringRealization:
    """A recurring realization of a holding over a window -- the recurring counterpart of a single
    `ScheduledRealization`. A scheduled withdrawal when `destination` is None (proceeds to the cash hub),
    a Roth conversion when `destination` is another holding's handle (pre-tax -> Roth). `amount` is the
    per-occurrence figure in today's dollars at `interval` cadence; the Forecast realizes, per interval,
    the annualized amount (per-occurrence x the interval's occurrences per year x the interval's share of
    the year), inflated to nominal, from the holding -- clamped to its value (a partial draw when short,
    never an overdraft). Annualized like a retirement contribution rather than counted per calendar date,
    so a given cadence realizes the same yearly total whether it is a contribution, a withdrawal, or a
    conversion. Applied in the accrual phase before the cash-management drawdown; tax, the early-withdrawal
    penalty, and RMDs follow the holding's class exactly as for a one-off realization."""

    holding     : Handle
    amount      : Decimal
    interval    : Duration
    window      : DateWindow         = DateWindow()
    destination : Optional[ Handle ] = None


def _occurrence_dates( *, window : DateWindow, interval : Duration, lo : date, hi : date ) -> list[ date ]:
    """The occurrence dates in `[lo, hi]` (inclusive) for a recurrence anchored at `window.start` and
    repeating every `interval`, kept within `window`. Shared by the recurring holding purchase (which
    expands per interval) and the recurring loan origination (which expands over the whole horizon)."""
    dates      = list()
    occurrence = window.start
    while occurrence <= hi:
        if occurrence >= lo and window.covers( occurrence ):
            dates.append( occurrence )
        occurrence = interval.add_to( occurrence )
        continue
    return dates


@dataclass( frozen = True )
class RecurringHoldingPurchase:
    """A recurring, inflation-indexed acquisition of a holding over a window at a cadence -- the
    asset-side analog of a recurring loan origination. At each occurrence the engine acquires
    `price` (today's dollars, inflated to that year's nominal from the forecast start) into the
    holding, funded from cash. When `trade_in` is set it first realizes the WHOLE existing holding
    to cash -- the depreciating-replacement pattern (a car cycled every N years, its depreciated
    value traded in); tax follows the holding's own class, so a personal DEPRECIATING asset trades
    in TAX_FREE with no asset-class special-casing here. Without `trade_in` it is a plain recurring
    investment, which serves an appreciating holding just as well.

    Unlike `RecurringRealization` (a continuous flow annualized across the year), a replacement is a
    discrete lump on a specific day: `occurrences_in` places each on its exact date so the
    whole-holding trade-in reads the right depreciated value and the run stays granularity-invariant.
    Occurrences anchor at `window.start` (the first purchase, required) and repeat every `interval`,
    bounded by `window.end`."""

    holding  : Handle
    price    : Decimal
    interval : Duration
    window   : DateWindow
    trade_in : bool = False

    def __post_init__( self ) -> None:
        if self.window.start is None:
            raise ValueError(
                'A recurring holding purchase needs a window start to anchor its occurrences.' )
        if self.interval.count < 1:
            raise ValueError( 'A recurring holding purchase needs a positive interval to advance.' )
        return

    def occurrences_in( self, span : DateSpan ) -> list[ date ]:
        """The occurrence dates falling in `span` -- the first at `window.start`, each `interval`
        later, bounded by the window. The engine owns the horizon, so it (not materialization)
        expands the compact intent into the concrete dates each interval sees."""
        return _occurrence_dates( window = self.window, interval = self.interval,
                                  lo = span.start_date, hi = span.end_date )


@dataclass( frozen = True )
class RecurringLoanOrigination:
    """A recurring loan origination over a window at a cadence -- the financing analog of a recurring
    holding purchase (a car refinanced at each replacement). At each occurrence the engine originates a
    fresh loan for `principal` (today's dollars, inflated to that year's nominal from the forecast start),
    scoped to its own per-cycle liability and interest accounts (`handle`/`interest_handle`, the cycle
    appended), and -- intrinsically -- pays off the prior cycle's loan at that date (the outgoing car's
    loan, cleared at trade-in). The loan terms (rate, term, interest class, extra principal) are the same
    each cycle, as for a t0 loan.

    The engine owns the horizon and the inflation, expanding this once at setup into the per-cycle
    `LoanParameters` and rollover payoffs so the existing origination/amortization machinery drives them
    unchanged; materialization declares only the recurring intent. Occurrences anchor at `window.start`
    (the first origination, required) and repeat every `interval`, bounded by `window.end`.

    The rollover settles the prior loan in the same span its replacement originates; that span's interest
    on the outgoing loan is charged across the whole span rather than only up to the payoff date -- a
    small, granularity-sensitive cost, immaterial for a nearly-amortized car loan."""

    name            : str
    principal       : Decimal
    interest_rate   : Rate
    term            : Duration
    interval        : Duration
    window          : DateWindow
    handle          : Handle
    interest_handle : Handle
    interest_class         : ExpenseTaxClass = ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST
    annual_extra_principal : Decimal         = Decimal( '0' )

    def __post_init__( self ) -> None:
        if self.window.start is None:
            raise ValueError(
                'A recurring loan origination needs a window start to anchor its occurrences.' )
        if self.interval.count < 1:
            raise ValueError( 'A recurring loan origination needs a positive interval to advance.' )
        return

    def occurrences_through( self, horizon : date ) -> list[ date ]:
        """The origination dates from `window.start` through `horizon` -- each `interval` apart, within
        the window. Expanded once at engine setup, since the loans need their accounts up front."""
        return _occurrence_dates( window = self.window, interval = self.interval,
                                  lo = self.window.start, hi = horizon )


class ScheduledEvent:
    """Base for a user-scheduled money-movement event: it references the holdings it touches by
    their planner-minted `Handle`, and the date it occurs, and resolves to a `PeriodEvent`
    (which holds the accounts) once the Forecast has built the books. `to_period_event` receives
    `holdings` (holding-handle string -> holding account) and the `Chart` (for the cash hub and
    other system/revenue accounts). Handles are matched by their string form, the identity
    contract, so any planner scheme works."""

    event_date : date

    def in_span( self, span : DateSpan ) -> bool:
        """Whether this event occurs within the interval `span`."""
        return span.start_date <= self.event_date <= span.end_date

    def to_period_event( self, holdings : dict[ str, Account ],
                         chart : Chart ) -> Optional[ PeriodEvent ]:
        """This event as a `PeriodEvent`, or None to skip it (e.g. a payoff whose loan account never
        materialized -- see `ScheduledLoanPayoff`)."""
        raise NotImplementedError

    def _cash( self, chart : Chart ) -> Account:
        """The cash hub the event moves value through, or a MissingAccountError."""
        cash = chart.cash_account()
        if cash is None:
            raise MissingAccountError( 'No cash account for the scheduled event.' )
        return cash

    def _holding( self, holdings : dict[ str, Account ], handle : Handle ) -> Account:
        """The holding account `handle` refers to, or a MissingAccountError if no such holding
        exists in the books (an event naming a holding the planner never created)."""
        holding = holdings.get( str( handle ) )
        if holding is None:
            raise MissingAccountError( f'No holding with handle "{handle}" for the scheduled event.' )
        return holding


@dataclass( frozen = True )
class ScheduledTransfer( ScheduledEvent ):
    """Move `amount` between two holdings (by handle), with no tax effect (e.g. cash -> CD, or a
    rebalance inside a tax-advantaged account)."""

    event_date : date
    source     : Handle
    target     : Handle
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        return Transfer(
            self.event_date, self._holding( holdings, self.source ),
            self._holding( holdings, self.target ), self.amount )


@dataclass( frozen = True )
class ScheduledLoanPayoff( ScheduledEvent ):
    """Pay off a loan's remaining balance (the loan by handle) at a date, funded from cash --
    extinguishing the liability so it stops amortizing. The amount is the loan's projected balance
    on the date, which the engine reads from the books; the planner supplies only the loan and the
    date. (A property sale that clears its mortgage is composed at the planning layer as a
    realization plus this payoff; this event itself knows nothing of the property link.)"""

    event_date : date
    loan       : Handle

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> Optional[ PeriodEvent ]:
        # A payoff whose loan account never materialized -- a sold vehicle whose loan has no terms yet, or a
        # loan already cleared -- has nothing to extinguish, so it is skipped rather than failing the run. A
        # handle that resolves to a non-liability is still a real wiring error.
        account = chart.account( self.loan )
        if account is None:
            return None
        if account.effective_account_type is not AccountType.LIABILITY:
            raise MissingAccountError(
                f'The account with handle "{self.loan}" is not a liability; a loan payoff needs one.' )
        return LoanPayoff( self.event_date, account, self._cash( chart ) )


@dataclass( frozen = True )
class ScheduledPurchase( ScheduledEvent ):
    """Acquire `amount` of a holding (by handle) at cost, funded from cash. The target holding
    must already be present from t0 (possibly opening at zero value)."""

    event_date : date
    asset      : Handle
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        return Purchase(
            self.event_date, self._cash( chart ), self._holding( holdings, self.asset ), self.amount )


@dataclass( frozen = True )
class ScheduledRealization( ScheduledEvent ):
    """Realize `amount` of a holding (by handle) -- a sale or pre-tax withdrawal when
    `destination` is None (proceeds to the cash hub), or a conversion when `destination` is
    another holding's handle (e.g. pre-tax -> Roth). `amount` of None realizes the entire holding
    (a full sale at its projected value); a value caps at the holding's market value. Tax treatment
    follows the source holding's class."""

    event_date  : date
    holding     : Handle
    amount      : Optional[ Decimal ] = None
    destination : Optional[ Handle ]  = None

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        target = self._cash( chart ) if self.destination is None else self._holding(
            holdings, self.destination )
        return Realization(
            self.event_date, self._holding( holdings, self.holding ), self.amount, target )


@dataclass( frozen = True )
class ScheduledPropertySale( ScheduledEvent ):
    """Sell a whole property (by handle) at a date, renting after or not (the residence choice; moot for a
    non-residence sale). The thin trigger the planning layer emits for a user-scheduled sale -- it carries
    no realize/payoff/expense machinery, only the handle, the date, and the choice, and the engine reaches
    the property's `PropertyData` to effect the sale. Resolves to a period `PropertySale`."""

    event_date : date
    holding    : Handle
    rent_after : bool = True

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        return PropertySale( self.event_date, self._holding( holdings, self.holding ), self.rent_after )


@dataclass( frozen = True )
class ScheduledExternalReceipt( ScheduledEvent ):
    """A one-time receipt of non-taxable value from outside, landing in cash -- a gift, or a US
    inheritance (non-taxable to the recipient, the estate tax being the estate's). Credits the
    External Receipts equity account and is never taxed. Taxable one-time income (a lottery win, a
    settlement) is instead a one-time `IncomeItem` (a `OneTime` cadence), crediting a revenue
    account and taxed at year-close. A recipient-side inheritance/estate tax regime (some
    jurisdictions) is not modeled."""

    event_date : date
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        equity = chart.system_account( SystemAccountRole.EXTERNAL_RECEIPTS )
        return ExternalReceipt( self.event_date, self._cash( chart ), equity, self.amount )


@dataclass( frozen = True )
class ScheduledExternalDisbursement( ScheduledEvent ):
    """A one-time gift of non-deductible value to outside, leaving cash -- a personal gift to
    family, say. The mirror of `ScheduledExternalReceipt`: debits the External Disbursements
    equity account, reducing net worth with no expense recognized and no tax effect. A deductible
    charitable gift is instead an `ExpenseItem` with `ExpenseTaxClass.CHARITABLE`."""

    event_date : date
    amount     : Decimal

    def to_period_event( self, holdings : dict[ str, Account ], chart : Chart ) -> PeriodEvent:
        equity = chart.system_account( SystemAccountRole.EXTERNAL_DISBURSEMENTS )
        return ExternalDisbursement( self.event_date, self._cash( chart ), equity, self.amount )


@dataclass( frozen = True )
class SubsidizedHealthCoverage:
    """Income-subsidized individual-market healthcare coverage over a `window` -- a general
    planning input named for the axis the model cares about (the income-based subsidy that
    couples healthcare cost to the income/tax projection), not for any one program. It is the
    privately-provided, individually-purchased, government-subsidized kind (the US ACA
    marketplace; employer and government-provided coverage are different buckets that need no
    node here). `household_size` is
    the covered tax-family size; `reference_premium` is the annual premium the subsidy is
    computed against, in today's dollars; `actual_premium` is the premium of the plan actually
    held, which caps the subsidy (the US PTC cannot exceed the premium paid). The Forecast hands
    the year's coverage to the tax engine, which (US) treats it as ACA enrollment and computes
    the premium tax credit; outside the window the household is uncovered (no subsidy). Coverage
    values are constant over the window."""

    window            : DateWindow
    household_size    : int
    reference_premium : Decimal
    actual_premium    : Decimal

    def covers( self, on_date : date ) -> bool:
        """Whether the household holds this coverage on `on_date`."""
        return self.window.covers( on_date )


@dataclass( frozen = True )
class SubjectRemoval:
    """A subject leaving the plan at `event_date` -- a death (a survivor transition for a
    couple). NOT a money-movement event: it posts no transaction. Instead the Forecast derives
    the tied consequences from this one fact -- the filing-status change (via the tax law's
    rule), the household-size decrement, the retitling of the decedent's accounts to the
    survivor, and dropping the subject from the tax context."""

    event_date     : date
    subject_handle : Handle


def resolve_household_size(
        base_size : int, removals : 'list[ SubjectRemoval ]', target_year : int ) -> int:
    """The household size in `target_year`: the base less every subject removed before that
    year (a removal takes effect the year after the death, like the subject drop). Household
    size is a Forecast concern, not tax law."""
    removed = sum( 1 for removal in removals if removal.event_date.year < target_year )
    return base_size - removed


@dataclass( frozen = True )
class AssetAllocation:
    """A target split of money across holdings, as `(account handle, weight)` pairs whose weights
    sum to 1 -- e.g. 40% stocks / 40% bonds / 20% CDs. By account *handle*, not asset class, for
    full flexibility (a planner can split across specific holdings, even two of the same class).
    Used to spread a cash sweep across a portfolio; reusable later for contribution allocation or
    rebalancing."""

    weights : tuple[ tuple[ Handle, Decimal ], ... ]

    def __post_init__( self ) -> None:
        if not self.weights:
            raise ValueError( 'An asset allocation needs at least one holding.' )
        if any( weight <= 0 for _handle, weight in self.weights ):
            raise ValueError( 'Asset-allocation weights must be positive.' )
        total = sum( ( weight for _handle, weight in self.weights ), Decimal( '0' ) )
        if total != Decimal( '1' ):
            raise ValueError( f'Asset-allocation weights must sum to 1, not {total}.' )
        return


@dataclass( frozen = True )
class CashAccountParameters:
    """How the cash hub is managed -- the band to keep it in and how. `cash_floor` is the
    minimum to maintain: a shortfall below it is covered by drawing (realizing) from the
    `draw_order` asset classes in priority. `cash_ceiling` is the maximum: surplus above it is
    swept into the `sweep_allocation` holdings (non-retirement) as investments at cost, so later
    sales tax only the gain. A None `cash_ceiling` (or `sweep_allocation`) disables sweeping."""

    cash_floor       : Decimal                     = Decimal( '0' )
    cash_ceiling     : Optional[ Decimal ]         = None
    draw_order       : list[ AssetClass ]          = field( default_factory = list )
    sweep_allocation : Optional[ AssetAllocation ] = None


@dataclass
class ForecastParameters:
    """The full materialized inputs for an N-step Forecast (see module docstring)."""

    start_date        : date
    end_date          : date
    filing_status     : FilingStatus
    statute      : StatuteProfile
    label             : str                                  = ''
    granularity       : Duration                             = Duration( 1, TimeUnit.YEAR )
    subjects          : list[ Subject ]                      = field( default_factory = list )
    assets            : list[ AssetParameters ]              = field( default_factory = list )
    economic_outlook  : EconomicOutlook                      = field( default_factory = EconomicOutlook )
    income_streams    : list[ IncomeStream ]                 = field( default_factory = list )
    income_items      : list[ IncomeItem ]                   = field( default_factory = list )
    expense_items     : list[ ExpenseItem ]                  = field( default_factory = list )
    expense_streams   : list[ ExpenseStream ]                = field( default_factory = list )
    loans             : list[ LoanParameters ]               = field( default_factory = list )
    contributions     : list[ RetirementContribution ]       = field( default_factory = list )
    recurring_realizations : list[ RecurringRealization ]    = field( default_factory = list )
    recurring_holding_purchases : list[ RecurringHoldingPurchase ] = field( default_factory = list )
    recurring_loan_originations : list[ RecurringLoanOrigination ] = field( default_factory = list )
    events            : list[ ScheduledEvent ]               = field( default_factory = list )
    property_data     : dict[ str, PropertyData ]            = field( default_factory = dict )
    cash_account      : CashAccountParameters                = field(
        default_factory = CashAccountParameters )
    health_coverage   : Optional[ SubsidizedHealthCoverage ] = None
    subject_removals  : list[ SubjectRemoval ]               = field( default_factory = list )
    property_sale_costs : TransactionCosts                   = field( default_factory = TransactionCosts )
    net_worth_calculation : NetWorthCalculation              = field( default_factory = NetWorthCalculation )
    initial_tax_state : Optional[ TaxState ]                 = None

    def __post_init__( self ) -> None:
        """Reject inputs that would silently mismodel. At most two filing subjects (a return has
        at most two adults); at most one cash hub (the funding/sweep model keys on a single CASH
        holding); a granularity that divides the year evenly. Loans amortize monthly regardless of
        granularity, so a loan term need not align to the period. The forecast must start on the
        first of a month -- `period_spans` is calendar-aligned, so any first-of-month start works (a
        mid-year start yields a partial first year, taxed by estimate)."""
        if len( self.subjects ) > 2:
            raise ValueError(
                f'At most two filing subjects are supported; got {len( self.subjects )}.' )
        cash_holdings = sum( 1 for asset in self.assets if asset.asset_class == AssetClass.CASH )
        if cash_holdings > 1:
            raise ValueError(
                f'At most one cash holding is supported (the cash hub); got {cash_holdings}.' )
        period_months = self.granularity.months()
        if 12 % period_months != 0:
            raise ValueError(
                f'The granularity must divide a year evenly; {period_months} months does not.' )
        if self.start_date.day != 1:
            raise ValueError(
                f'A forecast must start on the first of a month; got {self.start_date}.' )
        for loan in self.loans:
            if loan.origination_date is not None and loan.origination_date < self.start_date:
                raise ValueError(
                    f'An originated loan cannot originate before the forecast start; '
                    f'{loan.name} originates {loan.origination_date}, before {self.start_date}. '
                    f'For a loan present at t0, leave origination_date unset.' )
        return

    def earliest_removal_year( self ) -> Optional[ int ]:
        """The year of the first subject removal (the spouse death that drives the survivor
        filing transition), or None if no subject is removed."""
        if not self.subject_removals:
            return None
        return min( removal.event_date.year for removal in self.subject_removals )

    def active_subjects( self, year : int ) -> 'list[ Subject ]':
        """The subjects still present in `year`: a removed subject is present through the year
        of death and gone after, so age and SS stop the following year."""
        return [
            subject for subject in self.subjects
            if not self._is_removed_before( subject, year ) ]

    def survivor_handle( self, decedent_handle : Handle ) -> Optional[ Handle ]:
        """The handle of a subject other than `decedent_handle` -- whom the decedent's accounts
        retitle to. None if there is no other subject (the last death; the plan then ends)."""
        for subject in self.subjects:
            if ( subject.handle is not None ) and ( str( subject.handle ) != str( decedent_handle ) ):
                return subject.handle
        return None

    def _is_removed_before( self, subject : 'Subject', year : int ) -> bool:
        return any(
            ( str( removal.subject_handle ) == str( subject.handle ) )
            and ( removal.event_date.year < year )
            for removal in self.subject_removals )

    def period_spans( self ) -> list[ DateSpan ]:
        """The horizon sliced into `granularity` intervals, calendar-aligned: each calendar year
        is sliced from its own start, so no interval crosses December 31 -- the boundary the
        tax-year close, COLA indexing, and `year_fraction` proration all rely on. A mid-year
        start gives a partial first year (`[start, Dec 31]`); an `end_date` that is not December 31
        gives a partial last year; within a partial year the final interval clips to the year (or
        horizon) end. A January-1 start over whole years reproduces plain calendar years."""
        spans = list()
        for year in range( self.start_date.year, self.end_date.year + 1 ):
            window_start = max( self.start_date, date( year, 1, 1 ) )
            window_end   = min( self.end_date, date( year, 12, 31 ) )
            cursor = window_start
            while cursor <= window_end:
                following = self.granularity.add_to( cursor )
                spans.append( DateSpan( cursor, min( following - timedelta( days = 1 ), window_end ) ) )
                cursor = following
                continue
            continue
        return spans
