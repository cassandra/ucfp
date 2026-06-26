"""Typed in-memory shapes for the financial-facts domain.

The `Profile` aggregate and its parts are the structured, validated representation of a
user's facts; persistence (`models.py`) serializes the whole aggregate to JSON, so these
dataclasses -- not raw dicts -- are the only form the rest of the app handles.

Naming: a type that mirrors a Forecast engine concept keeps the engine noun with a
`Profile` suffix (`SubjectProfile` <-> `Subject`) -- continuity across the materialization
boundary, while staying a distinct type the profile layer owns (so the stored format is
decoupled from engine churn). A type with no single engine analog -- the engine is
deliberately generic for income and expenses -- takes its own user-facing name
(`SalaryEntitlement`, `CommittedObligation`). Shared vocabulary (enums, `Rate`, `Duration`)
is imported from the engine; engine parameter dataclasses are not.

Section comments mark the user-facing groupings; they are kept as a seam guide for a future
breakdown, without (yet) a wrapper type per section.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from common.rate import Rate
from common.recurrence import Duration

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, RealPropertyType
from ucfp.forecast.parameters import WindowedAmount
from ucfp.tax.enums import FilingStatus


# Handles are stable string identities other sections reference; never display names. The subject
# handles are canonical here -- the profile mints them and the scenario, interview, and engine
# materialization all refer back to these, never a re-typed literal.
PRIMARY_SUBJECT_HANDLE = 'subject'
PARTNER_SUBJECT_HANDLE = 'partner'

# The residence asset and rent obligation the home section mints, shared with the spending section.
RESIDENCE_ASSET_HANDLE = 'residence'
RENT_OBLIGATION_HANDLE = 'rent'


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
    materialization supplies the domain-required 0. Growth is a scenario assumption. Cash is
    a CASH-class asset."""
    handle: str
    name: str
    asset_class: AssetClass
    opening_value: Decimal
    cost_basis: Optional[ Decimal ] = None
    owner_handle: Optional[ str ] = None
    property: Optional[ PropertyProfile ] = None


# --- What you owe ---------------------------------------------------------

@dataclass( frozen = True )
class LoanProfile:
    """A loan contract, stored as a person knows it: when it started (`origination_date`), the
    `original_amount` borrowed, the `interest_rate`, and the `original_term`. The balance still
    owed at the forecast start -- and the remaining term -- are *derived* by materialization
    (amortizing from origination), unless `current_balance` overrides the balance, the way to
    capture extra principal already paid down. Future extra-principal payments are a scenario
    strategy, not here. `interest_class` (e.g. residence mortgage) defaults at materialization
    when omitted. `property_handle` attaches the loan to the property it finances, so a property
    sale can find and end it; None for a non-property loan."""
    handle: str
    name: str
    origination_date: date
    original_amount: Decimal
    interest_rate: Rate
    original_term: Duration
    current_balance: Optional[ Decimal ] = None
    interest_class: Optional[ ExpenseTaxClass ] = None
    property_handle: Optional[ str ] = None


# --- Income entitlements --------------------------------------------------
# The engine models all income as a generic IncomeStream keyed by tax class; the profile
# diverges to entitlement *facts*, each composed with a scenario date-knob into a realized
# stream at materialization.

@dataclass( frozen = True )
class SalaryEntitlement:
    """Today's wage level. Raises and the stop date are scenario knobs."""
    subject_handle: str
    annual_amount: Decimal


@dataclass( frozen = True )
class PensionEntitlement:
    """Base benefit and the age it is quoted at. The realized benefit depends on the
    scenario start-date knob via plan reduction terms (detailed terms deferred)."""
    subject_handle: str
    base_annual_amount: Decimal
    normal_start_age: int


@dataclass( frozen = True )
class GovernmentPensionEntitlement:
    """A subject's accrued state retirement-pension benefit, as the monthly amount payable at
    the jurisdiction's normal retirement age (the US PIA at full retirement age, the UK State
    Pension, ...). Named for the axis, not the US program -- the jurisdiction-neutral
    counterpart of the engine's `SubsidizedHealthCoverage`. The realized benefit depends on the
    scenario's claiming-age knob via the jurisdiction's adjustment schedule
    (`tax.government_pension`)."""
    subject_handle: str
    monthly_at_normal_age: Decimal


# --- Rental income --------------------------------------------------------

@dataclass( frozen = True )
class RentalIncome:
    """Gross rent a rental property produces, bound to its property by `property_handle`. `schedule`
    is the monthly amount over time spans -- a `WindowedAmount` per span (one open-ended row is a
    constant rent), the same shape an expense flow uses; a sale ends it by capping the schedule at
    the sale date. The income is reported by the property's owner and materializes to a monthly
    recurring `GROSS_RENTAL` income item, grown by the rental-increase rate."""
    property_handle: str
    schedule: list[ WindowedAmount ]


# --- Committed obligations ------------------------------------------------

@dataclass( frozen = True )
class CommittedObligation:
    """A determined (non-discretionary) non-loan outflow -- rent, premium, tuition, property
    tax. The fact subset of the engine's generic expense flows. `cadence` keeps the natural
    period (rent is monthly); `through` bounds a time-limited commitment."""
    handle: str
    name: str
    amount: Decimal
    cadence: Duration
    expense_tax_class: ExpenseTaxClass
    through: Optional[ date ] = None


# --- Aggregate ------------------------------------------------------------

@dataclass( frozen = True )
class Profile:
    """The user's full set of facts, grouped by user-facing section. Serialized whole into a
    `Profile` record's JSON, and materialized with a Scenario into `ForecastParameters`."""
    # People
    subjects: list[ SubjectProfile ] = field( default_factory = list )
    filing_status: Optional[ FilingStatus ] = None
    # What you own
    assets: list[ AssetProfile ] = field( default_factory = list )
    # What you owe
    loans: list[ LoanProfile ] = field( default_factory = list )
    # Income entitlements
    salaries: list[ SalaryEntitlement ] = field( default_factory = list )
    pensions: list[ PensionEntitlement ] = field( default_factory = list )
    government_pension: list[ GovernmentPensionEntitlement ] = field( default_factory = list )
    # Rental income
    rental_incomes: list[ RentalIncome ] = field( default_factory = list )
    # Committed obligations
    obligations: list[ CommittedObligation ] = field( default_factory = list )
