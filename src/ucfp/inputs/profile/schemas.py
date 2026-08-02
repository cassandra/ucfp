"""Typed in-memory shapes for the financial-facts domain.

The `Profile` aggregate and its parts are the structured, validated representation of a
user's facts; persistence (`models.py`) serializes the whole aggregate to JSON, so these
dataclasses -- not raw dicts -- are the only form the rest of the app handles.

Naming: a type that mirrors a Forecast engine concept keeps the engine noun with a
`Profile` suffix (`SubjectProfile` <-> `Subject`) -- continuity across the materialization
boundary, while staying a distinct type the profile layer owns (so the stored format is
decoupled from engine churn). A type with no single engine analog -- the engine is
deliberately generic for income and expenses -- takes its own user-facing name
(`IncomeFlow`). Shared vocabulary (enums, `Duration`) is imported from the engine;
engine parameter dataclasses are not.

Section comments mark the user-facing groupings; they are kept as a seam guide for a future
breakdown, without (yet) a wrapper type per section.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from common.rate import Rate, ZERO_RATE
from common.recurrence import Duration

from ucfp.accounts.enums import AssetClass, IncomeTaxClass, RealPropertyType
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType
from ucfp.jurisdiction.us.subdivision_tax import USState

from .enums import DebtKind, HousingTenure


# Handles are stable string identities other sections reference; never display names. The subject
# handles are canonical here -- the profile mints them and the plans, interview, and engine
# materialization all refer back to these, never a re-typed literal.
PRIMARY_SUBJECT_HANDLE = 'subject'
PARTNER_SUBJECT_HANDLE = 'partner'

# The per-subject retirement account handles: `{prefix}{subject handle}`. The Accounts step mints them
# (one pre-tax and one Roth per subject, always present at $0), and materialization resolves a Roth
# conversion's target by them -- so the prefix lives here, referred back to, never re-typed as a literal.
PRETAX_ACCOUNT_HANDLE_PREFIX = 'pretax-'
ROTH_ACCOUNT_HANDLE_PREFIX   = 'roth-'

# The residence asset the home section mints, and the stable identity of a tenant's rented home --
# a synthetic handle (there is no owned asset behind it) that keys the rented-home column and its
# overrides in the property-expenses matrix. Both are shared with the Home Expenses step.
RESIDENCE_ASSET_HANDLE = 'residence'
RENTED_HOME_HANDLE     = 'rented-home'
# The mortgage debt secured against the residence, minted by the home section and surfaced (read-only)
# in the Debts section. A rental's mortgage handle is derived from its own property handle instead.
RESIDENCE_MORTGAGE_HANDLE = 'residence-mortgage'


# --- People ---------------------------------------------------------------

@dataclass( frozen = True )
class SubjectProfile:
    """A household member. Mirrors the engine `Subject` (identical fields)."""
    handle: str
    name: str
    birthdate: date


# --- What you own ---------------------------------------------------------

@dataclass( frozen = True )
class PropertyProfile:
    """Real-estate specifics for §121/§1250, carried only by real-estate assets. Mirrors
    the engine `PropertyAttributes`."""
    acquisition_date: date
    depreciable_basis: Decimal
    property_type: RealPropertyType


@dataclass( frozen = True )
class AssetProfile:
    """A holding at t0 -- the fact subset of the engine `AssetParameters`: class, opening
    value, and (for taxable holdings) cost basis. Zero-basis classes omit basis, and
    materialization supplies the domain-required 0. Growth is an Assumptions economic factor.
    Cash is a CASH-class asset."""
    handle: str
    name: str
    asset_class: AssetClass
    opening_value: Decimal
    cost_basis: Optional[ Decimal ] = None
    owner_handle: Optional[ str ] = None
    property: Optional[ PropertyProfile ] = None


# --- What you owe ---------------------------------------------------------

@dataclass( frozen = True )
class Debt:
    """A debt as a fact: its `kind`, a `name`, and the current `balance` owed -- and nothing about
    how it will be repaid. Everything about the future (rate, term, extra principal, payoff, or a
    monthly-servicing expense) is a Plans strategy, composed with this balance at materialization;
    that is why we ask the *current* balance directly rather than an original amount (which would
    amortize wrong once it has been paid down). An amortizing kind becomes a real loan on the balance
    sheet; the trigger kind (a credit card) is not materialized here -- it drives the debt plan.
    `secured_asset` links a mortgage to the property it finances (so a sale can end it); None
    otherwise."""
    handle: str
    name: str
    kind: DebtKind
    balance: Decimal
    secured_asset: Optional[ str ] = None


# --- Income flows ---------------------------------------------------------
# Income the household receives -- the income twin of the Plans' `ExpenseFlow`. A flow is a
# fact (its amount over time), plural and independent per subject. Social Security and pensions are
# the exception: their amount is actuarially derived from the claiming/start timing, so they stay
# entitlement facts below, not flows.

@dataclass( frozen = True )
class IncomeFlow:
    """One income the household receives -- salary, consulting, rental rent, or other ordinary
    income -- the income twin of the Plans' `ExpenseFlow`. `handle` is its stable identity, which the
    Plans' income timing references. `subject_handle` is who receives it (for per-subject tax, e.g. the
    per-worker wage cap), or None for household income (rent, which the engine taxes as one aggregate);
    `income_tax_class` its treatment; `amount` its level in today's dollars, a fact the engine grows and
    gates to the window; `interval` None is a smoothed stream, a `Duration` an item placed at that cadence
    (rent is monthly). `property_handle` ties rental income to its property -- carried through to the engine
    so a sale ends it and per-property tax can key on it; None for non-property income.

    The *window* the income is active over (start/stop) is a **plan**, not a fact -- it lives in the Plans'
    per-flow `IncomeTiming` keyed by `handle`, not here. A subject may have several flows (shifting jobs,
    overlapping incomes)."""
    handle: str
    name: str
    subject_handle: Optional[ str ]
    income_tax_class: IncomeTaxClass
    amount: Decimal
    interval: Optional[ Duration ] = None
    property_handle: Optional[ str ] = None


# --- Retirement entitlements ----------------------------------------------
# Social Security and pensions stay entitlement *facts* (the benefit at normal age), each composed
# with a Plans timing knob into a realized stream at materialization -- because the benefit
# amount depends on when it is claimed.

@dataclass( frozen = True )
class PensionEntitlement:
    """Base benefit and the age it is quoted at. The realized benefit depends on the
    Plans start-date knob via plan reduction terms (detailed terms deferred)."""
    subject_handle: str
    base_annual_amount: Decimal
    normal_start_age: int


@dataclass( frozen = True )
class GovernmentPensionEntitlement:
    """A subject's accrued state retirement-pension benefit, as the monthly amount payable at
    the jurisdiction's normal retirement age (the US PIA at full retirement age, the UK State
    Pension, ...). Named for the axis, not the US program -- the jurisdiction-neutral
    counterpart of the engine's `SubsidizedHealthCoverage`. The realized benefit depends on the
    Plans claiming-age knob via the jurisdiction's adjustment schedule
    (`tax.government_pension`)."""
    subject_handle: str
    monthly_at_normal_age: Decimal


# --- Aggregate ------------------------------------------------------------

@dataclass( frozen = True )
class Profile:
    """The user's full set of facts, grouped by user-facing section. Serialized whole into a
    `Profile` record's JSON, and materialized with Plans and Assumptions into
    `ForecastParameters`."""
    # People
    subjects: list[ SubjectProfile ] = field( default_factory = list )
    filing_status: Optional[ FilingStatus ] = None
    # How the household holds its home. Owning is also carried by the residence asset; renting and the
    # rent-free case have no asset, so this fact carries them (and gates the rented-home housing costs).
    home_tenure: HousingTenure = HousingTenure.OWN
    # The household's tax jurisdiction -- a fact these facts are all expressed under (account tax
    # classes, entitlements, filing status). US federal is the only one modeled today.
    jurisdiction_type: JurisdictionType = JurisdictionType.US_FEDERAL
    # The household's US state and its simplified income-tax rate (a flat rate on federal AGI). The
    # state is a UI convenience that auto-fills the rate; the rate is the source of truth the engine
    # reads (user-overridable). None state / zero rate = no state income tax modeled.
    us_state: Optional[ USState ] = None
    state_income_tax_rate: Rate = ZERO_RATE
    # What you own
    assets: list[ AssetProfile ] = field( default_factory = list )
    # What you owe
    debts: list[ Debt ] = field( default_factory = list )
    # Income flows
    income_flows: list[ IncomeFlow ] = field( default_factory = list )
    # Retirement entitlements
    pensions: list[ PensionEntitlement ] = field( default_factory = list )
    government_pension: list[ GovernmentPensionEntitlement ] = field( default_factory = list )
