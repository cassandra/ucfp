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

from .enums import CadenceDomain, ExpenseCategory, ExpenseClass, PropertyContext, Realization


@dataclass( frozen = True )
class EconomicOutlookSchedule:
    """An economic outlook as a schedule of windowed `EconomicParameters` segments (the engine's
    own rate type). A constant outlook is a single unbounded segment; time-varying rates are more
    segments. Materialization wraps it into the engine's `EconomicOutlook`."""
    segments: list[ EconomicParameters ] = field( default_factory = list )


@dataclass( frozen = True )
class ExpenseType:
    """One catalog expense. Two orthogonal groupings place it: `expense_class` is its applicability scope
    (which planning surface shows it -- `LIVING`/`PROPERTY`/`VEHICLE`), and `category` is its visual group
    (the ordered section it renders under within that surface). `order` is its position among the items of
    its category; a row sorts by (category declaration order, `order`), so the deliberate (group, item)
    order is independent of how the catalog source is authored.

    `expense_tax_class`, the seeded `interval` (its default cadence), a single `default_amount` at that
    cadence, and the two cadence attributes follow. `realization` (fixed) decides how it hits the engine
    -- `SMOOTH` annualizes and spreads it, `DISCRETE` places it at its cadence; `cadence_domain` (the
    input domain) decides which cadences the user may re-select.

    For a `PROPERTY` row, `expense_tax_class` is the row's *personal* class (`LIVING`, or `SALT` for
    property tax); materialization swaps it to `RENTAL_EXPENSE` for a rental-owned property. `applies_to`
    names the `PropertyContext`s the row seeds against -- e.g. a roof against every owned dwelling,
    utilities also against a rented home, property management only against a rental. It is empty for a
    row outside the `PROPERTY` class. A tuple, not a set, because the JSON codec round-trips tuples.

    `handle` is the row's stable identity -- an authored slug independent of the mutable `name`/`order`,
    carried onto the plan expense and stamped on the materialized account, so the run table can map an
    output account back to its catalog row (and thus its class/category/order) for input-aligned
    grouping."""
    name: str
    handle: str
    expense_class: ExpenseClass
    category: ExpenseCategory
    order: int
    expense_tax_class: ExpenseTaxClass
    default_amount: Decimal
    interval: Duration
    realization: Realization
    cadence_domain: CadenceDomain
    applies_to: tuple[ PropertyContext, ... ] = ()
    # A tenant-paid property row (utilities the tenant, not the landlord, ordinarily pays): its per-rental
    # cell defaults to $0 so a rental does not carry the residence utility amount (see the property-
    # expenses merge). False for landlord-borne and non-property rows.
    tenant_paid: bool = False
    # A "durable" expense the user enters as `count` items at `cost_each` replaced every `lifespan`
    # years; a calculator fills the amount = count x cost_each / lifespan (its annualized cost). All
    # None for a normal expense entered as a single amount.
    count: Optional[ int ] = None
    cost_each: Optional[ Decimal ] = None
    lifespan: Optional[ int ] = None


@dataclass( frozen = True )
class ExpenseCatalog:
    """The curated set of expense types -- the payload of an EXPENSE_CATALOG set, seeded from the
    spreadsheet data and the source of presumed defaults for the spending section."""
    expenses: list[ ExpenseType ] = field( default_factory = list )
