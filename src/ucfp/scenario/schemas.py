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

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.parameter_sets.enums import EconomicOutlookVariant, LifestyleLevel, LifestyleScope
from ucfp.tax.law import TaxForecastProfile

from .enums import PlannedMoveKind


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
    """The date knobs for one subject. `government_pension_claiming_age` and `pension_start`
    select into that subject's profile entitlement facts, so the realized benefits are derived
    rather than stored."""
    subject_handle: str
    retirement_date: Optional[ date ] = None
    salary_stop: Optional[ date ] = None
    government_pension_claiming_age: Optional[ int ] = None
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


# --- Saving ---------------------------------------------------------------

@dataclass( frozen = True )
class Contribution:
    """A recurring retirement contribution -- mirrors the engine `RetirementContribution`.
    `account_handle` targets a profile holding; `source` sets its tax treatment."""
    account_handle: str
    annual_amount: Decimal
    source: ContributionSource
    through: Optional[ date ] = None


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


# --- Planned moves --------------------------------------------------------

@dataclass( frozen = True )
class PlannedMove:
    """A one-off balance-sheet move on a date -- the engine's scheduled-event family
    (transfer, purchase, realization, external gift in/out) as one type keyed by `kind`. The
    fields in play depend on the kind; the family may split into distinct types later."""
    kind: PlannedMoveKind
    date: date
    amount: Decimal
    source_handle: Optional[ str ] = None
    target_handle: Optional[ str ] = None


# --- Life events ----------------------------------------------------------

@dataclass( frozen = True )
class AssumedDeath:
    """An assumed subject death driving the survivor transition -- mirrors the engine
    `SubjectRemoval`."""
    subject_handle: str
    event_date: date


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
    # External factors (see note above)
    economic_outlook: EconomicOutlookVariant = EconomicOutlookVariant.EXPECTED
    tax_forecast: Optional[ TaxForecastProfile ] = None
    # Timing
    timing: list[ RetirementTiming ] = field( default_factory = list )
    # Lifestyle
    lifestyle: Optional[ LifestylePlan ] = None
    # Saving
    contributions: list[ Contribution ] = field( default_factory = list )
    # Drawdown
    drawdown: Optional[ DrawdownPolicy ] = None
    # Planned moves
    planned_moves: list[ PlannedMove ] = field( default_factory = list )
    # Life events
    assumed_deaths: list[ AssumedDeath ] = field( default_factory = list )
    health_coverage: Optional[ HealthCoverageAssumption ] = None
