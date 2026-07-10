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

from .enums import CreditCardPlanMode, EventKind


# ===== Personal choices (the levers a user turns) =====

# --- Timing ---------------------------------------------------------------

@dataclass( frozen = True )
class RetirementTiming:
    """Per-subject benefit-election timing -- the dates Social Security and a pension are claimed /
    started. Each selects into that subject's profile entitlement facts, so the realized benefit is
    derived from the entitlement plus the election rather than stored. (A wage's end is no longer a
    retirement date here -- it lives on the wage's own income line.)"""
    subject_handle: str
    government_pension_claiming_date: Optional[ date ] = None
    pension_start: Optional[ date ] = None


# --- Recurring expenses ---------------------------------------------------
# The user's regular (non-property) recurring expenses, each seeded from the curated catalog (its
# category, tax class, and cadence) with an amount per span. The spans are the Plans' shared
# `expense_spans` timeline (until-ages relative to the primary subject); `amounts` aligns 1:1 with it.

@dataclass( frozen = True )
class RecurringExpense:
    """One regular recurring expense: its name, catalog `category`, tax class, `interval` (its cadence),
    `realization` (how it hits the engine -- smoothed vs placed at its cadence), and an `amounts` list --
    one amount per span of the Plans' shared `expense_spans` timeline (a single amount when no spans are
    defined). Property operating expenses are a separate class (`PropertyExpense`)."""
    name: str
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


# --- Saving ---------------------------------------------------------------

@dataclass( frozen = True )
class Contribution:
    """A recurring retirement contribution -- mirrors the engine `RetirementContribution`.
    `account_handle` targets a profile holding; `source` sets its tax treatment."""
    account_handle: str
    annual_amount: Decimal
    source: ContributionSource
    through: Optional[ date ] = None


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


# --- Auto (car ownership) -------------------------------------------------
# The household's vehicles as one plan: the shared `num_cars`, the (optional) purchase/financing
# pattern, and the per-car `running_costs`. `num_cars` is the anchor both aspects scale by, so a running
# cost is entered once per car and multiplied at materialization. Purchase and running costs are
# independent aspects -- either may be set without the other (an incomplete plan simply materializes
# whichever aspects are complete).

@dataclass( frozen = True )
class VehicleRunningCost:
    """One per-car vehicle running cost (fuel, insurance, maintenance, repair). `amount` is the cost per
    car at its `interval` cadence; materialization multiplies it by the plan's `num_cars`. `realization`
    (smoothed vs placed at its cadence) and `cadence_domain` (the editable input domain) mirror the
    general expense model, but the amount is a single per-car figure -- constant, with no age spans.
    `amount` is None when blank (the cost is then not charged)."""
    name: str
    expense_tax_class: ExpenseTaxClass
    interval: Duration
    amount: Optional[ Decimal ] = None
    realization: Realization = Realization.SMOOTH
    cadence_domain: CadenceDomain = CadenceDomain.FIXED


@dataclass( frozen = True )
class VehiclePlan:
    """The household's ongoing car-ownership costs, smoothed so the forecast carries no start/stop
    lumps. Every `recurrence_years` from `start_date`, `num_cars` cars are bought at `purchase_price`
    each. Unfinanced (no down or monthly payment given), the whole price lands as a lump each cycle.
    Financed, the down payment lands as the lump and the financed remainder -- principal plus interest
    at an assumed auto-loan rate/term -- is spread evenly over the recurrence period as one constant
    expense (no start/stop). The user gives either the `monthly_payment` or the `down_payment`;
    materialization derives the other. `start_date` is solicited (pre-filled from an existing auto
    loan's end date), so the recurring costs begin where any current loan leaves off.

    `num_cars` is the shared quantity feeding both the purchase pattern and the per-car `running_costs`.
    Every field is optional: the plan persists to carry whichever aspect the user has begun (purchase,
    running costs, or just the car count), and materialization emits only the complete aspects."""
    num_cars: Optional[ int ] = None
    purchase_price: Optional[ Decimal ] = None
    recurrence_years: Optional[ int ] = None
    start_date: Optional[ date ] = None
    monthly_payment: Optional[ Decimal ] = None
    down_payment: Optional[ Decimal ] = None
    running_costs: list[ VehicleRunningCost ] = field( default_factory = list )


# --- Drawdown -------------------------------------------------------------

@dataclass( frozen = True )
class DrawdownPolicy:
    """The cash band and how to cover/sweep it -- mirrors the engine `CashAccountParameters`.
    Below the floor the engine draws from `draw_order`; above the ceiling it sweeps surplus
    into `sweep_allocation` (holding handle -> weight, weights summing to 1)."""
    cash_floor: Decimal = Decimal( '0' )
    cash_ceiling: Optional[ Decimal ] = None
    draw_order: list[ AssetClass ] = field( default_factory = list )
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


# --- Life events ----------------------------------------------------------

@dataclass( frozen = True )
class HealthCoverageAssumption:
    """An assumed income-subsidized (ACA-style) health-coverage premium credit -- mirrors the
    engine `SubsidizedHealthCoverage`."""
    household_size: int
    reference_premium: Decimal
    start: Optional[ date ] = None
    through: Optional[ date ] = None


# --- Aggregate ------------------------------------------------------------

@dataclass( frozen = True )
class Plans:
    """One named set of the user's contemplated future, grouped by section. Serialized whole into a
    `Plans` record's JSON, and materialized (with a Profile and Assumptions) into
    `ForecastParameters`."""
    # Timing
    timing: list[ RetirementTiming ] = field( default_factory = list )
    # Recurring expenses (regular, non-property) and the shared span timeline (until-ages, last None)
    expense_spans: list[ Optional[ int ] ] = field( default_factory = lambda: [ None ] )
    recurring_expenses: list[ RecurringExpense ] = field( default_factory = list )
    # Property operating expenses (one shared set with per-property overrides)
    property_expenses: list[ PropertyExpense ] = field( default_factory = list )
    # Saving
    contributions: list[ Contribution ] = field( default_factory = list )
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
