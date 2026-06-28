"""Typed payloads for each parameter-set kind.

A `ParameterSet`'s `data` JSON is one of these typed aggregates (keyed by kind in `registry`),
serialized through the dataclass codec. Schedule-shaped from the start: a value that can vary
over time is a list of windowed segments, never a lone instance.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from common.recurrence import Duration

from ucfp.accounts.enums import ExpenseTaxClass
from ucfp.forecast.economic_outlook import EconomicParameters

from .enums import ExpenseCategory, LifestyleLevel


@dataclass( frozen = True )
class EconomicOutlookSchedule:
    """An economic outlook as a schedule of windowed `EconomicParameters` segments (the engine's
    own rate type). A constant outlook is a single unbounded segment; time-varying rates are more
    segments. Materialization wraps it into the engine's `EconomicOutlook`."""
    segments: list[ EconomicParameters ] = field( default_factory = list )


@dataclass( frozen = True )
class LifestyleAmounts:
    """A lifestyle expense's value at each level -- the uniform low/medium/high selector indexes
    here. Per occurrence for an item, annual for a stream."""
    low: Decimal
    medium: Decimal
    high: Decimal

    def for_level( self, level : LifestyleLevel ) -> Decimal:
        return { LifestyleLevel.LOW: self.low, LifestyleLevel.MEDIUM: self.medium,
                 LifestyleLevel.HIGH: self.high }[ level ]


@dataclass( frozen = True )
class LifestyleExpense:
    """One discretionary expense category: a name, a low/medium/high value triple, a tax class,
    and a cadence. `interval` None is a stream (an annual magnitude, smoothed); a `Duration` is
    an item placed at that recurrence (weekly gas, an every-ten-years car) -- never amortized."""
    name: str
    amounts: LifestyleAmounts
    expense_tax_class: ExpenseTaxClass = ExpenseTaxClass.LIVING
    interval: Optional[ Duration ] = None


@dataclass( frozen = True )
class LifestyleCostTable:
    """A curated table of discretionary expenses -- the payload of a LIFESTYLE_COSTS set. The
    scenario's lifestyle level selects each expense's value; materialization steps it over the
    schedule timeline."""
    expenses: list[ LifestyleExpense ] = field( default_factory = list )


@dataclass( frozen = True )
class ExpenseType:
    """One catalog expense: its `category` (the user-facing bucket and the decision it attaches to),
    tax class, cadence, and a single `default_amount` -- the typical value (annual for a stream,
    per-occurrence for an item). `lifestyle_dependent` marks the ones whose amount a user would vary
    over time; `interval` None is a smoothed stream, a `Duration` an item placed at its cadence."""
    name: str
    category: ExpenseCategory
    expense_tax_class: ExpenseTaxClass
    default_amount: Decimal
    interval: Optional[ Duration ] = None
    lifestyle_dependent: bool = False


@dataclass( frozen = True )
class ExpenseCatalog:
    """The curated set of expense types -- the payload of an EXPENSE_CATALOG set, seeded from the
    spreadsheet data and the source of presumed defaults for the spending section."""
    expenses: list[ ExpenseType ] = field( default_factory = list )
