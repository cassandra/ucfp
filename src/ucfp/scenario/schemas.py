"""Typed in-memory shapes for the planning-assumptions domain.

The `Scenario` aggregate and its parts are the structured, validated representation of a
user's assumptions; persistence (`models.py`) serializes the whole aggregate to JSON, so
these dataclasses -- not raw dicts -- are the only form the rest of the app handles.

Same naming rule as the profile layer: a type mirroring a Forecast engine concept keeps the
engine noun (`Contribution` <-> `RetirementContribution`); a knob with no single engine
analog takes its own user-facing name (`RetirementTiming`, `LifestylePlan`). The engine is
deliberately general for income/expenses, so most personal-choice knobs here are
presentation-original.

The two **external factors** (economic outlook, tax) are exogenous engine concepts with no
user-facing reframing, so they *reuse the engine's own types* -- `EconomicParameters` and
`TaxForecastProfile` -- rather than a parallel scenario type, keeping the scenario in
lockstep with exactly what the engine projects under (no arbitrary subset, no silent drift).

Section comments mark the two groupings -- exogenous external factors vs the personal
choices a user turns -- kept as a seam guide for a future breakdown.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from common.recurrence import Duration

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.forecast.parameters import ContributionSource, WindowedAmount
from ucfp.parameter_sets.enums import ExpenseCategory, LifestyleLevel, LifestyleScope
from ucfp.jurisdiction.law import TaxForecastProfile

from .enums import EventKind


# ===== External factors (exogenous -- about the world, not the user) =====
# Economic outlook is a *reference* to a curated set in the parameter-set library, chosen by
# `EconomicOutlookVariant` (Optimistic / Expected / Pessimistic); the actual rates live in the
# library (admin-curated, schedule-shaped) and are loaded at materialization -- so reasonable
# defaults come from the database, never zero-filled here. Tax reuses the engine's own
# `TaxForecastProfile` (a future kind may move it into the library too).


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


# --- Lifestyle ------------------------------------------------------------
# The discretionary cost table itself is curated in the parameter-set library (chosen by
# `LifestyleScope`); the scenario holds only the personal timeline of levels that selects each
# expense's value over time. The first segment's level applies from the start of the horizon.

@dataclass( frozen = True )
class LifestyleSegment:
    """A span beginning at `start` over which one lifestyle level applies."""
    start: date
    level: LifestyleLevel


@dataclass( frozen = True )
class LifestylePlan:
    """A reference to a curated cost table (`scope`) plus the timeline of levels (`segments`)
    that selects each expense's value over the horizon."""
    scope: LifestyleScope = LifestyleScope.GENERAL
    segments: list[ LifestyleSegment ] = field( default_factory = list )


# --- Spending -------------------------------------------------------------
# The new expense model: the user's planned expenses, each seeded from the curated catalog (so it
# carries the catalog's category, tax class, and cadence) with the user's amount. Supersedes the
# lifestyle cost-table above, which is retired once this reaches parity.

@dataclass( frozen = True )
class ExpenseFlow:
    """One planned expense -- its name, catalog `category`, tax class, cadence (`interval`), and a
    `schedule`: the amount over time spans, a `WindowedAmount` per span (one open-ended row is a
    constant amount; reuses the engine's segment type, so it materializes with no conversion).
    `interval` None is a smoothed stream, a `Duration` an item placed at that cadence;
    `lifestyle_dependent` marks the ones a user would vary over time. `property_handle` attaches an
    operating expense to the property it belongs to (so a sale can find and end it); None for a
    general living expense."""
    name: str
    category: ExpenseCategory
    expense_tax_class: ExpenseTaxClass
    schedule: list[ WindowedAmount ]
    interval: Optional[ Duration ] = None
    lifestyle_dependent: bool = False
    property_handle: Optional[ str ] = None


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
class LoanPrepayment:
    """A planned recurring extra-principal payment on a loan, beyond its scheduled payment, paying
    it down faster. `loan_handle` targets a profile loan; `annual_amount` is the extra principal
    per year (mirrors the engine's `LoanParameters.annual_extra_principal`)."""
    loan_handle: str
    annual_amount: Decimal


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
class Scenario:
    """One named set of assumptions, grouped by section. Serialized whole into a `Scenario`
    record's JSON, and materialized with a Profile into `ForecastParameters`."""
    # External factors (see note above): the scenario's own editable copy of the economic rates
    # (seeded from a library preset, then user-owned) and the tax forecast.
    economics: Optional[ EconomicParameters ] = None
    tax_forecast: Optional[ TaxForecastProfile ] = None
    # Timing
    timing: list[ RetirementTiming ] = field( default_factory = list )
    # Lifestyle
    lifestyle: Optional[ LifestylePlan ] = None
    # Spending
    expenses: list[ ExpenseFlow ] = field( default_factory = list )
    # Saving
    contributions: list[ Contribution ] = field( default_factory = list )
    # Loan paydown
    prepayments: list[ LoanPrepayment ] = field( default_factory = list )
    # Drawdown
    drawdown: Optional[ DrawdownPolicy ] = None
    # Plan events (§7)
    events: list[ PlanEvent ] = field( default_factory = list )
    # Life events
    health_coverage: Optional[ HealthCoverageAssumption ] = None
