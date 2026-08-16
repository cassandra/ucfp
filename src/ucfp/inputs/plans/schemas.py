"""Typed in-memory shapes for the Plans domain -- the user's contemplated future.

The `Plans` aggregate and its parts are the structured, validated representation of the personal
choices a user turns (timing, spending, saving, paydown, drawdown, events); persistence
(`models.py`) serializes the whole aggregate to JSON, so these dataclasses -- not raw dicts -- are
the only form the rest of the app handles. The exogenous external factors (economic outlook, tax)
are a separate `Assumptions` aggregate, not held here.

Same naming rule as the profile layer: a type mirroring a Forecast engine concept keeps the
engine noun (`Contribution` <-> `RetirementContribution`); a knob with no single engine
analog takes its own user-facing name (`RetirementTiming`, `LifestylePlan`). The engine is
deliberately general for income/expenses, so most personal-choice knobs here are
presentation-original.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from common.rate import Rate
from common.recurrence import Duration

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.parameter_sets.enums import CadenceDomain, ExpenseCategory, PropertyContext, Realization

from .enums import (
    CreditCardPlanMode, EventKind, LeaseDispositionKind, PaymentMethod, VehicleDispositionKind )


# ===== Personal choices (the levers a user turns) =====

# --- Timing ---------------------------------------------------------------

@dataclass( frozen = True )
class RetirementTiming:
    """Per-subject benefit-election timing -- the dates Social Security and a pension are claimed /
    started. Each selects into that subject's profile entitlement facts, so the realized benefit is
    derived from the entitlement plus the election rather than stored. (A wage's start/stop is not a
    retirement date here -- it lives in `IncomeTiming`, keyed to the flow.)"""
    subject_handle: str
    government_pension_claiming_date: Optional[ date ] = None
    pension_start: Optional[ date ] = None


@dataclass( frozen = True )
class IncomeTiming:
    """When one income flow is active -- the *plan* over a Profile income *fact* (`IncomeFlow`), keyed to
    it by `flow_handle`. `start`/`end` are optional and editable: no start means from the forecast's
    start, no end means for life -- so a fact-defined income can be given a planned stop, or a future
    start (a stopgap for future income until a dedicated recurring money-in event exists)."""
    flow_handle: str
    start: Optional[ date ] = None
    end: Optional[ date ] = None


# --- Recurring expenses ---------------------------------------------------
# The household's `LIVING`-class recurring expenses, each seeded from the curated catalog (its
# category, tax class, and cadence) with an amount per span. The spans are the Plans' shared
# `expense_spans` timeline (until-ages relative to the primary subject); `amounts` aligns 1:1 with it.

@dataclass( frozen = True )
class RecurringExpense:
    """One regular recurring expense: its name, catalog `category`, tax class, `interval` (its cadence),
    `realization` (how it hits the engine -- smoothed vs placed at its cadence), and an `amounts` list --
    one amount per span of the Plans' shared `expense_spans` timeline (a single amount when no spans are
    defined). Property operating expenses are a separate class (`PropertyExpense`)."""
    name: str
    handle: str
    category: ExpenseCategory
    expense_tax_class: ExpenseTaxClass
    amounts: list[ Decimal ]
    interval: Duration
    realization: Realization = Realization.SMOOTH
    cadence_domain: CadenceDomain = CadenceDomain.FIXED
    # A durable entered as a count of items at a cost each, replaced every `lifespan` years (remembered
    # calculator inputs); the amount is their annualized cost. All None for a normal expense.
    count: Optional[ int ] = None
    cost_each: Optional[ Decimal ] = None
    lifespan: Optional[ int ] = None


# --- Property expenses ----------------------------------------------------
# A dwelling's operating expenses: one shared set of amounts applied to every property the expense's
# `applies_to` reaches, with per-property overrides where they differ. Constant over the forecast (no
# spans); each property instance ends at that property's sale, clipped at materialize. Distinct from the
# recurring expenses above.

@dataclass( frozen = True )
class PropertyExpense:
    """One property operating expense across the household's properties: its name, catalog `category`,
    the *personal* `expense_tax_class` (materialization derives the rental swap), `interval` (its
    cadence), `realization` (smoothed vs placed at its cadence), and the `applies_to` property contexts
    it reaches. `default_amount` (None when blank) applies to every reached property unless `overrides`
    gives that property (by handle) its own amount; a property with neither is not charged. Amounts are
    constant; a sale ends a property's instance at materialize."""
    name: str
    handle: str
    category: ExpenseCategory
    expense_tax_class: ExpenseTaxClass
    applies_to: tuple[ PropertyContext, ... ]
    interval: Duration
    realization: Realization = Realization.SMOOTH
    cadence_domain: CadenceDomain = CadenceDomain.FIXED
    default_amount: Optional[ Decimal ] = None
    overrides: dict[ str, Decimal ] = field( default_factory = dict )
    # A durable entered as a count of items at a cost each, replaced every `lifespan` years (remembered
    # calculator inputs); the shared default amount is their annualized cost. All None for a normal one.
    count: Optional[ int ] = None
    cost_each: Optional[ Decimal ] = None
    lifespan: Optional[ int ] = None

    @property
    def tenure_invariant( self ) -> bool:
        """Whether this expense carries across the primary dwelling's own->rent transition: true iff it
        applies to both the owned residence and a rented home (utilities -- you pay them either way), so a
        residence sale that becomes a rental keeps it. Own-only rows (property tax, upkeep) and rent-only
        rows (rent) do not. Derived from `applies_to` so it cannot drift from the contexts that
        authoritatively define where the expense applies."""
        return { PropertyContext.RESIDENCE, PropertyContext.RENTED_HOME }.issubset( self.applies_to )


# --- Saving ---------------------------------------------------------------

@dataclass( frozen = True )
class Contribution:
    """A planned recurring retirement contribution: a per-occurrence `amount` at `interval` cadence into
    the retirement holding `account_handle`, over an optional age window (`start_age`/`end_age` -- the
    account owner's age; no start = from now, no end = indefinitely). `source` sets the money source and
    deductibility (see the engine `ContributionSource`). Materialization annualizes it (occurrences/year
    x amount) and resolves the ages to a date window for the engine `RetirementContribution`. `handle` is
    a stable per-row identity (minted `contribution-N`)."""
    handle: str
    account_handle: str
    amount: Decimal
    source: ContributionSource
    interval: Duration
    start_age: Optional[ int ] = None
    end_age: Optional[ int ] = None


# --- Tax planning ---------------------------------------------------------

@dataclass( frozen = True )
class RothConversion:
    """A planned Roth conversion of pre-tax retirement money to the source owner's Roth account. One-time
    (a single `start_age`, no `interval`) or recurring (an `interval` cadence over the owner's age window
    `start_age`/`end_age` -- no start = from now, no end = indefinitely). `amount` is the per-occurrence
    conversion in today's dollars, inflation-indexed. `source_handle` is the pre-tax account converted
    from; the Roth target is that owner's Roth (always present, so not restated). `handle` is a stable
    per-row identity (minted `conversion-N`)."""
    handle: str
    source_handle: str
    amount: Decimal
    interval: Optional[ Duration ] = None
    start_age: Optional[ int ] = None
    end_age: Optional[ int ] = None


@dataclass( frozen = True )
class Withdrawal:
    """A planned scheduled withdrawal from a pre-tax retirement account to cash -- a deliberate tax lever
    (bracket-filling, RMDs, pre-conversion draws), taxed as ordinary income, landing in cash before the
    automatic cash-management drawdown. One-time (a single `start_age`, no `interval`) or recurring (an
    `interval` cadence over the owner's age window `start_age`/`end_age` -- no start = from now, no end =
    indefinitely). `amount` is the per-occurrence draw in today's dollars, inflation-indexed; it is bounded
    by the account's value (a partial draw when short). `source_handle` is the pre-tax account drawn from.
    `handle` is a stable per-row identity (minted `withdrawal-N`)."""
    handle: str
    source_handle: str
    amount: Decimal
    interval: Optional[ Duration ] = None
    start_age: Optional[ int ] = None
    end_age: Optional[ int ] = None


# --- Loan paydown ---------------------------------------------------------

@dataclass( frozen = True )
class LoanRepayment:
    """How an amortizing debt is repaid: the `interest_rate` and `remaining_term`, seeded from the
    contract (the default being to follow it), keyed to a Profile `Debt` by `debt_handle`. Composed
    with the debt's current balance at materialization into the engine's amortizing loan. Extra
    principal is a separate `LoanPrepayment`; a lump-sum payoff is a Plans event."""
    debt_handle: str
    interest_rate: Rate
    remaining_term: Duration


@dataclass( frozen = True )
class LoanPrepayment:
    """A planned recurring extra-principal payment on a debt, beyond its scheduled payment, paying it
    down faster. `loan_handle` targets a Profile `Debt` by handle; `annual_amount` is the extra
    principal per year (mirrors the engine's `LoanParameters.annual_extra_principal`)."""
    loan_handle: str
    annual_amount: Decimal


@dataclass( frozen = True )
class CreditCardPlan:
    """How a credit-card `Debt` will be paid down -- the Plans side of a card, which never becomes a
    loan on the books. Stored as intent (a `mode` and its one input); materialization resolves it, at
    an assumed card APR, into a recurring paydown expense and/or a one-time payoff, so the stored plan
    never goes stale against the balance. MONTHLY carries `monthly_payment`; BY_DATE and LUMP carry
    `target_date`. `card_handle` keys it to the `Debt`."""
    card_handle: str
    mode: CreditCardPlanMode
    monthly_payment: Optional[ Decimal ] = None
    target_date: Optional[ date ] = None


# --- Auto (car ownership): a list of vehicles (each with its own dates/financing) and shared running costs.

@dataclass( frozen = True )
class VehicleRunningCost:
    """One per-car vehicle running cost (fuel, insurance, maintenance, repair). `amount` is the cost per
    car at its `interval` cadence; materialization applies it to each vehicle over its ownership window,
    so the total tracks the number of cars owned at any time. `realization` (smoothed vs placed at its
    cadence) and `cadence_domain` (the editable input domain) mirror the general expense model, but the
    amount is a single per-car figure -- constant, with no age spans. `amount` is None when blank (the
    cost is then not charged)."""
    name: str
    handle: str
    expense_tax_class: ExpenseTaxClass
    interval: Duration
    amount: Optional[ Decimal ] = None
    realization: Realization = Realization.SMOOTH
    cadence_domain: CadenceDomain = CadenceDomain.FIXED


@dataclass( frozen = True )
class Vehicle:
    """A recurring vehicle purchase over a window: bought at `purchase_price` on `purchase_date` and
    replaced every `recurrence_years` thereafter, up to `end_date` (blank = ongoing). It is used two
    ways -- as a **net-new** future vehicle the household adds, and as the **replacement** a `Replace`
    disposition buys when a current vehicle is retired (see `VehicleDisposition`). `payment_method` sets
    how each purchase is modeled and which payment fields apply:

    - CASH: no payment fields -- the whole price buys an owned, depreciating asset each cycle.
    - LOAN: `down_payment` is paid up front and the remainder is financed; `monthly_payment` is
      optional (materialization derives it from price, down, and the assumed auto rate/term, or the
      down from the monthly, whichever the user gave).
    - LEASE: `down_payment` is the first payment, `monthly_payment` the recurring lease payment, and
      `lease_end_payment` the disposition/turn-in cost -- no ownership, no trade-in.

    `handle` is a stable per-vehicle identity (a net-new mints `vehicle-N`; a replacement's is derived
    from the current vehicle it succeeds); every other field is optional so a just-added vehicle persists
    while it is filled -- materialization emits its purchases only once `purchase_date`, `purchase_price`,
    and `recurrence_years` are all set, and its running costs while it is owned."""
    handle: str
    name: str = ''
    purchase_date: Optional[ date ] = None
    end_date: Optional[ date ] = None
    purchase_price: Optional[ Decimal ] = None
    recurrence_years: Optional[ int ] = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    down_payment: Optional[ Decimal ] = None
    monthly_payment: Optional[ Decimal ] = None
    lease_end_payment: Optional[ Decimal ] = None

    @property
    def has_structural_terms( self ) -> bool:
        """Whether the user-entered *structure* of the purchase is set -- the fields a purchase needs
        besides its date (a net-new vehicle sets the date directly; a disposition supplies it from its
        handover). A cash or financed purchase needs a price and a replacement interval. A lease is not
        bought, so it needs no price; instead its `monthly_payment` -- its defining cost -- is required,
        alongside the interval. Other amounts (a down/first payment, a lease-end payment) stay optional --
        a blank is a legitimate zero, not a missing field."""
        if self.payment_method is PaymentMethod.LEASE:
            return self.recurrence_years is not None and self.monthly_payment is not None
        return self.purchase_price is not None and self.recurrence_years is not None

    @property
    def is_materializable( self ) -> bool:
        """Whether this vehicle has all it needs to emit its purchases -- its structural terms plus a
        purchase date. Until then it contributes nothing (a partial, still-being-entered vehicle)."""
        return self.purchase_date is not None and self.has_structural_terms


@dataclass( frozen = True )
class VehicleDisposition:
    """What the household plans to do with one **current** vehicle, keyed to its Profile handle by
    `vehicle_handle` -- the vehicle plan's per-vehicle input, mirroring a debt's `LoanRepayment`. `kind`
    selects the fate; the absence of a stored disposition means KEEP (the vehicle depreciates in place,
    running to the horizon), so only a non-default choice is recorded. `sale_date` is the sale/handover
    date, used by SELL and REPLACE. `replacement` is the successor a REPLACE buys -- a fully-formed
    `Vehicle` whose `purchase_date` is this `sale_date`, so it materializes exactly as a net-new vehicle
    does; it is None for KEEP and SELL. (Not named `date`: a dataclass field named the same as its type,
    with a default, shadows the type when annotations are resolved, so it would not deserialize.)"""
    vehicle_handle: str
    kind: VehicleDispositionKind
    sale_date: Optional[ date ] = None
    replacement: Optional[ Vehicle ] = None

    @property
    def is_complete( self ) -> bool:
        """Whether this disposition has the structural fields it needs to fully materialize -- so an
        incomplete one is a safe no-op (the vehicle stays retained), never a partial, misleading
        projection. KEEP needs nothing; SELL needs its handover date; REPLACE needs that date and a
        replacement carrying its structural terms (the date becomes the replacement's purchase date).
        Amounts stay optional."""
        if self.kind is VehicleDispositionKind.KEEP:
            return True
        if self.kind is VehicleDispositionKind.SELL:
            return self.sale_date is not None
        return ( self.sale_date is not None
                 and self.replacement is not None and self.replacement.has_structural_terms )


@dataclass( frozen = True )
class LeasedVehicleDisposition:
    """The current lease terms and end-of-term plan for one **leased** vehicle, keyed to its Profile
    `LeasedVehicle` by `vehicle_handle` -- the leased twin of `VehicleDisposition`. `monthly` and
    `lease_end` are the current lease's cost and end (its terms live here, mirroring a loan's rate/term in
    the Debt plan), so the lease materializes only once they are set. `kind` is what happens at term end:
    RETURN ends the monthly there (no successor); RENEW, BUY_CASH, and BUY_LOAN each hand over at
    `lease_end` to a `successor` -- a fully-formed `Vehicle` beginning then, materialized as any plan
    vehicle is, whose payment method the kind fixes (a recurring lease for RENEW, a recurring cash or
    financed purchase for a buy). `successor` is set for every kind but RETURN."""
    vehicle_handle: str
    monthly: Optional[ Decimal ] = None
    lease_end: Optional[ date ] = None
    kind: LeaseDispositionKind = LeaseDispositionKind.RETURN
    successor: Optional[ Vehicle ] = None

    @property
    def successor_ready( self ) -> bool:
        """Whether the end-of-term successor has what it needs to materialize -- its own structural terms
        plus the `lease_end` it begins at -- *independent* of the current lease's cost. A successor
        materializes on this alone, so an unpriced-yet current lease never suppresses a fully-entered
        renewal or purchase; a Return, which has no successor, is never ready."""
        return ( self.kind is not LeaseDispositionKind.RETURN and self.lease_end is not None
                 and self.successor is not None and self.successor.has_structural_terms )

    @property
    def is_complete( self ) -> bool:
        """Whether this leased disposition has the structural fields it needs to fully materialize -- an
        incomplete one is a safe no-op (the lease does not enter the projection yet). The current lease's
        `monthly` (its defining cost) and `lease_end` (where every kind hands over or ends) are always
        required; a successor kind (RENEW, BUY_CASH, BUY_LOAN) also needs its successor ready."""
        if self.lease_end is None or self.monthly is None:
            return False
        return self.kind is LeaseDispositionKind.RETURN or self.successor_ready


@dataclass( frozen = True )
class VehiclePlan:
    """The household's car-ownership plan: per-current-vehicle `dispositions` (what happens to each car
    the household owns today), per-current-*leased*-vehicle `leased_dispositions` (each lease's terms and
    what happens at term end), the net-new `vehicles` it adds over time (each with its own
    purchase/replacement schedule, ownership window, and optional financing), and the shared per-car
    `running_costs` applied to each vehicle while it is operated. Purchases are smoothed within each
    vehicle's window (a lump every recurrence, plus a constant financed-cost stream when financed); the
    running costs track the fleet as vehicles are added and retired. Every list is optional so the plan
    persists whichever aspect the user has begun, and materialization emits only the complete parts."""
    dispositions: list[ VehicleDisposition ] = field( default_factory = list )
    leased_dispositions: list[ LeasedVehicleDisposition ] = field( default_factory = list )
    vehicles: list[ Vehicle ] = field( default_factory = list )
    running_costs: list[ VehicleRunningCost ] = field( default_factory = list )


# --- Drawdown -------------------------------------------------------------

@dataclass( frozen = True )
class DrawdownPolicy:
    """The cash band and how to cover/sweep it -- mirrors the engine `CashAccountParameters`.
    Below the floor the engine draws from `draw_order`; above the ceiling it sweeps surplus
    into `sweep_allocation` (holding handle -> weight, weights summing to 1).

    `draw_order` is the full ordered list of every draw source; `retained` marks the ones the user
    has held back (kept, never sold). A retained source keeps its slot in the order -- so re-enabling
    restores its priority -- but materialization drops it before the engine, which therefore only ever
    sees the enabled sources and never learns of a retained one."""
    cash_floor: Decimal = Decimal( '0' )
    cash_ceiling: Optional[ Decimal ] = None
    draw_order: list[ AssetClass ] = field( default_factory = list )
    retained: list[ AssetClass ] = field( default_factory = list )
    sweep_allocation: list[ tuple[ str, Decimal ] ] = field( default_factory = list )


# --- Plan events ----------------------------------------------------------

@dataclass( frozen = True )
class PlanEvent:
    """One dated event the user adds in §7 -- a money move or a life event. `kind` selects its
    `EventType` handler (which references it needs, how it materializes into the engine);
    `selections` maps each required role (subject, source/target account, ...) to the chosen
    entity handle. A best-effort authoring convenience: once added it is just another input the
    run reads, never a simulation step. `amount` is None for an event that carries no sum (a
    death)."""
    kind: EventKind
    date: date
    amount: Optional[ Decimal ] = None
    selections: dict[ str, str ] = field( default_factory = dict )
    # Event-specific non-entity settings a kind may read (distinct from `selections`, which are entity
    # handles): a small key->value bag, e.g. a residence sale's 'rent_after'. Absent keys take the kind's
    # default, so an event stored before a kind grew an option still materializes.
    options: dict[ str, str ] = field( default_factory = dict )


# --- Life events ----------------------------------------------------------

@dataclass( frozen = True )
class HealthCoverageAssumption:
    """An assumed income-subsidized (ACA-style) health-coverage premium credit -- mirrors the
    engine `SubsidizedHealthCoverage`. `actual_premium` is the premium of the plan actually held
    (which caps the credit); left unset it defaults to `reference_premium` at materialization --
    i.e. assume enrollment in the benchmark plan, so the cap does not bind until a cheaper plan is
    given."""
    household_size: int
    reference_premium: Decimal
    actual_premium: Optional[ Decimal ] = None
    start: Optional[ date ] = None
    through: Optional[ date ] = None


# --- Aggregate ------------------------------------------------------------

@dataclass( frozen = True )
class Plans:
    """One named set of the user's contemplated future, grouped by section. Serialized whole into a
    `Plans` record's JSON, and materialized (with a Profile and Assumptions) into
    `ForecastParameters`."""
    # Timing: per-subject entitlement elections, and per-flow income start/stop windows
    timing: list[ RetirementTiming ] = field( default_factory = list )
    income_timing: list[ IncomeTiming ] = field( default_factory = list )
    # Recurring expenses (`LIVING`-class) and the shared span timeline (until-ages, last None)
    expense_spans: list[ Optional[ int ] ] = field( default_factory = lambda: [ None ] )
    recurring_expenses: list[ RecurringExpense ] = field( default_factory = list )
    # Property operating expenses (one shared set with per-property overrides)
    property_expenses: list[ PropertyExpense ] = field( default_factory = list )
    # Saving
    contributions: list[ Contribution ] = field( default_factory = list )
    # Tax planning: Roth conversions (pre-tax -> Roth) and scheduled withdrawals (pre-tax -> cash),
    # each one-time or a recurring ladder
    roth_conversions: list[ RothConversion ] = field( default_factory = list )
    withdrawals: list[ Withdrawal ] = field( default_factory = list )
    # Loan repayment (rate/term per amortizing debt) and extra-principal paydown
    loan_repayments: list[ LoanRepayment ] = field( default_factory = list )
    prepayments: list[ LoanPrepayment ] = field( default_factory = list )
    # Credit-card paydown plans (per card, resolved to expenses at materialization)
    credit_card_plans: list[ CreditCardPlan ] = field( default_factory = list )
    # The household's car-ownership costs (smoothed to expenses at materialization)
    vehicle_plan: Optional[ VehiclePlan ] = None
    # Drawdown
    drawdown: Optional[ DrawdownPolicy ] = None
    # Plan events (§7)
    events: list[ PlanEvent ] = field( default_factory = list )
    # Life events
    health_coverage: Optional[ HealthCoverageAssumption ] = None
