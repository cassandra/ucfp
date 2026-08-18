"""The pluggable, country-agnostic tax interface.

A `TaxEngine` is a black box to the Period: given the fiscal window's ledger facts,
the resolved taxpayer context, and the opening tax state (carryforwards), it returns
the charges to book, any credits, and the updated tax state. Everything
jurisdiction-specific -- the taxpayer-context shape, the tax-state shape, parameters,
brackets, rules -- lives in a country package (e.g. `jurisdiction/us/`); this module stays
neutral. The `tax_context` and `tax_state` passed through `assess` are therefore
engine-specific and opaque here.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Protocol

from common.date_span import DateSpan
from ucfp.accounts.books import Account
from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass

from .context import TaxContext


class TaxState:
    """Marker base for a jurisdiction's threaded tax carryforward state. The neutral layer and the
    Period only *thread* it between periods (a fiscal year's `closing_tax_state` becomes the next
    year's `opening_tax_state`); they never read its members. The concrete fields (e.g. the US
    capital-loss carryover) live in the country package's subclass, so this stays an opaque,
    field-less base -- a named type in place of bare `object`."""


class TaxFigures:
    """Marker base for a jurisdiction's derived tax figures (e.g. AGI/MAGI) an assessment carries
    for downstream consumers. Opaque to the neutral layer; the concrete shape lives in the country
    package's subclass."""


class FiscalWindowView( Protocol ):
    """The read-only view of one fiscal year's books the engine assesses against -- the structural
    contract that `period`'s `FiscalWindow` satisfies. Declared here rather than imported because
    the dependency runs period -> tax: the engine names the shape it reads without depending on
    (or cycling through) the concrete window class."""

    @property
    def span( self ) -> DateSpan:
        ...

    def income( self, income_tax_class : IncomeTaxClass ) -> Decimal:
        ...

    def income_by_account( self, income_tax_class : IncomeTaxClass ) -> list[ Decimal ]:
        ...

    def income_for_owner( self, income_tax_class : IncomeTaxClass, owner_handle ) -> Decimal:
        ...

    def expense( self, expense_tax_class : ExpenseTaxClass ) -> Decimal:
        ...

    def holdings( self ) -> list[ Account ]:
        ...

    def opening_value( self, holding : Account ) -> Decimal:
        ...

    def distributions_to_cash( self, holding : Account ) -> Decimal:
        ...

    def contributions_from_cash( self, holding : Account ) -> Decimal:
        ...


@dataclass( frozen = True )
class TaxCharge:
    """A tax to pay: an amount attributed to an expense tax-class, which the Period
    accrues as owed to the tax payable, settled to cash the following year. `detail` is a
    human-readable memo explaining this layer's own drivers (mirroring `TaxPenalty.reason`),
    which the Period posts as the accrual's description."""

    tax_class : ExpenseTaxClass
    amount    : Decimal
    detail    : str = ''


@dataclass( frozen = True )
class TaxCredit:
    """A refundable credit the Period books against `tax_class` (e.g. the ACA premium
    tax credit against income tax) -- the reverse of a charge, refundable so a credit
    beyond the matching tax yields a net refund. `detail` is a human-readable memo
    explaining the credit's drivers, which the Period posts as the accrual's description."""

    tax_class : ExpenseTaxClass
    amount    : Decimal
    detail    : str = ''


@dataclass( frozen = True )
class TaxPenalty:
    """A per-event tax penalty the engine assessed against one money-movement: the `tax_class`
    it is paid into, the `amount`, and a human-readable `reason` the Period surfaces as a
    Notice so the charge is explained (e.g. a 10% early-withdrawal penalty on a named
    account). Distinct from a `TaxCharge` -- which is the year's aggregate assessment -- in
    being one-per-event and carrying its rationale."""

    tax_class : ExpenseTaxClass
    amount    : Decimal
    reason    : str


@dataclass( frozen = True )
class ForcedTransaction:
    """A transaction the tax law forces this interval -- an RMD today: distribute `amount`
    out of `account` (to cash), with a `reason` the Period surfaces as a Notice. The engine
    determines these (reading the books view); the Period executes each as a realization."""

    account : Account
    amount  : Decimal
    reason  : str


@dataclass( frozen = True )
class TaxAssessment:
    """The result of `TaxEngine.assess`: the `charges` to book and refundable `credits`
    to apply, plus `closing_tax_state` -- the engine's updated threaded tax state to
    carry forward as the next fiscal year's `opening_tax_state` (None for engines that
    thread no state) -- and `figures`, engine-specific derived figures (e.g. AGI/MAGI)
    for downstream consumers. `closing_tax_state` and `figures` are opaque to the Period
    and to this neutral module: their concrete types (the US `TaxState` / `TaxFigures`) live in
    the country package and subclass the neutral marker bases here, so the agnostic layer names
    the type without depending on a specific jurisdiction."""

    charges           : list[ TaxCharge ]    = field( default_factory = list )
    credits           : list[ TaxCredit ]    = field( default_factory = list )
    closing_tax_state : Optional[ TaxState ] = None
    figures           : Optional[ TaxFigures ] = None


class ContributionKind( Enum ):
    """Which annual retirement-contribution limit a contribution counts against. The two buckets
    have separate limits and aggregate independently per person: an employer-sponsored plan (US
    401(k)/403(b)) versus a personal account (US IRA, traditional or Roth). An employer match
    counts against neither employee limit, so such a contribution carries no kind. Neutral here;
    a jurisdiction maps its account types onto these buckets."""

    EMPLOYER_PLAN = 'employer_plan'
    PERSONAL      = 'personal'


class TaxEngine:
    """A tax-calculation strategy. Subclasses implement `assess`; the tax-year calendar
    defaults to the civil year and is overridden by a jurisdiction on a different fiscal
    year. The Period owns one engine every interval and asks it when to settle, rather than
    being handed a pre-decided window -- the boundary is the tax law's to know."""

    def assess( self, fiscal_window : FiscalWindowView, tax_context : TaxContext,
                opening_tax_state : Optional[ TaxState ] ) -> TaxAssessment:
        raise NotImplementedError

    def assess_employment_tax( self, fiscal_window : FiscalWindowView, tax_context : TaxContext ) -> Decimal:
        """The employee employment tax (US FICA: Social Security + Medicare) on the wages in
        `fiscal_window` -- distinct from income tax. It is withheld as wages are earned, so the Period
        pays it to cash in-year rather than deferring it to the tax payable -- hence its own entry
        point, separate from `assess`. The window is year-to-date, so the annual figures (the Social
        Security wage cap, the Medicare surtax threshold) apply against cumulative wages and a caller
        pays the increment not yet withheld. Default: none."""
        return Decimal( '0' )

    def estimate_income_tax( self, fiscal_window : FiscalWindowView, tax_context : TaxContext,
                             opening_tax_state : Optional[ TaxState ] ) -> Decimal:
        """The income tax to prepay in-year as a safe-harbor estimate, before the year's true
        liability is settled to the payable. Withholding income tax through the year (rather than
        floating the whole bill to next April) matches reality; the year-end settlement then trues it
        up on the payable. Default: none (the whole liability defers)."""
        return Decimal( '0' )

    def assess_penalties( self, fiscal_window : FiscalWindowView,
                          tax_context : TaxContext ) -> list[ TaxPenalty ]:
        """The `TaxPenalty`s the year's activity incurs (e.g. the early-withdrawal penalty),
        read from the books view `fiscal_window` (balances, distributions) and `tax_context`
        (owner ages). Default: none. The engine owns the whole rule -- which distributions
        qualify and the rate -- reading the books rather than being handed pre-digested data."""
        return []

    def forced_transactions( self, fiscal_window : FiscalWindowView,
                             tax_context : TaxContext ) -> list[ ForcedTransaction ]:
        """The `ForcedTransaction`s the tax law requires this interval (e.g. RMDs), read from
        the books view `fiscal_window` (balances, distributions) and `tax_context` (owner
        ages). Default: none. The engine owns the whole rule -- which accounts, the amount,
        the reconciliation -- so the Period only executes what comes back."""
        return []

    def contribution_limit( self, kind : ContributionKind, age : int ) -> Optional[ Decimal ]:
        """The annual employee contribution limit for a `kind` of retirement contribution at this
        owner `age` (any age-based catch-up already folded in), or None for no limit. The Forecast
        leverages this to keep contributions within the law -- rejecting an over-limit input at
        build and clamping a contribution that outgrows its limit mid-forecast. Default: None (a
        neutral engine imposes no limit)."""
        return None

    def closes_tax_year( self, on_date : date ) -> bool:
        """Whether a tax year ends on `on_date` -- the interval on which the Period settles
        tax. Civil-year default: December 31."""
        return ( on_date.month == 12 ) and ( on_date.day == 31 )

    def tax_year_bounds( self, on_date : date ) -> tuple[ date, date ]:
        """The (start, end) dates of the tax year containing `on_date` -- the full span the
        engine assesses over. Civil-year default: January 1 to December 31 of that year."""
        return ( date( on_date.year, 1, 1 ), date( on_date.year, 12, 31 ) )

    def tax_payment_date( self, tax_year : int ) -> date:
        """The date `tax_year`'s assessed tax is settled to cash -- the return's filing/payment
        day, the year after the income is earned, so the payment (and any draw funding it) falls
        in the following tax year. Civil-year default: April 15 of `tax_year` + 1."""
        return date( tax_year + 1, 4, 15 )


class ZeroTaxEngine( TaxEngine ):
    """Country-neutral stand-in that assesses no tax, so the Period flow can be
    exercised end to end before a real engine exists."""

    def assess( self, fiscal_window : FiscalWindowView, tax_context : TaxContext,
                opening_tax_state : Optional[ TaxState ] ) -> TaxAssessment:
        return TaxAssessment()
