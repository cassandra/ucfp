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

from .enums import ExpenseCategory, PropertyContext


@dataclass( frozen = True )
class EconomicOutlookSchedule:
    """An economic outlook as a schedule of windowed `EconomicParameters` segments (the engine's
    own rate type). A constant outlook is a single unbounded segment; time-varying rates are more
    segments. Materialization wraps it into the engine's `EconomicOutlook`."""
    segments: list[ EconomicParameters ] = field( default_factory = list )


@dataclass( frozen = True )
class ExpenseType:
    """One catalog expense: its `category` (the user-facing bucket and the decision it attaches to),
    tax class, cadence, and a single `default_amount` -- the typical value (annual for a stream,
    per-occurrence for an item). `interval` None is a smoothed stream, a `Duration` an item placed at
    its cadence.

    For a `PROPERTY` row, `expense_tax_class` is the row's *personal* class (`LIVING`, or `SALT` for
    property tax); materialization swaps it to `RENTAL_EXPENSE` for a rental-owned property. `applies_to`
    names the `PropertyContext`s the row seeds against -- e.g. a roof against every owned dwelling,
    utilities also against a rented home, property management only against a rental. It is empty for a
    non-property (household) row. A tuple, not a set, because the JSON codec round-trips tuples."""
    name: str
    category: ExpenseCategory
    expense_tax_class: ExpenseTaxClass
    default_amount: Decimal
    interval: Optional[ Duration ] = None
    applies_to: tuple[ PropertyContext, ... ] = ()


@dataclass( frozen = True )
class ExpenseCatalog:
    """The curated set of expense types -- the payload of an EXPENSE_CATALOG set, seeded from the
    spreadsheet data and the source of presumed defaults for the spending section."""
    expenses: list[ ExpenseType ] = field( default_factory = list )
