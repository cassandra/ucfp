"""The pluggable, country-agnostic tax interface.

A `TaxEngine` is a black box to the Period: given the fiscal window's ledger facts,
the resolved taxpayer context, and the opening tax state (carryforwards), it returns
the charges to book, any credits, and the updated tax state. Everything
jurisdiction-specific -- the taxpayer-context shape, the tax-state shape, parameters,
brackets, rules -- lives in a country package (e.g. `tax/us/`); this module stays
neutral. The `tax_context` and `tax_state` passed through `assess` are therefore
engine-specific and opaque here.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.enums import ExpenseTaxClass


@dataclass( frozen = True )
class TaxCharge:
    """A tax to pay: an amount attributed to an expense tax-class, which the Period
    posts as a tax expense drawn from cash."""

    tax_class : ExpenseTaxClass
    amount    : Decimal


@dataclass( frozen = True )
class TaxCredit:
    """A refundable credit the Period books against `tax_class` (e.g. the ACA premium
    tax credit against income tax) -- the reverse of a charge, refundable so a credit
    beyond the matching tax yields a net refund."""

    tax_class : ExpenseTaxClass
    amount    : Decimal


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
class TaxEventCandidate:
    """A money-movement presented to the engine for any per-event tax consequence (the
    early-withdrawal penalty today). Neutral: the Period reports *every* movement and the
    engine owns the entire filter -- it reads what it needs off the accounts (source and
    destination asset class, the source's owner) and the `amount`. `source` is the account
    the value leaves; `destination` the one it enters."""

    source      : Account
    destination : Account
    amount      : Decimal


@dataclass( frozen = True )
class TaxAssessment:
    """The result of `TaxEngine.assess`: the `charges` to book and refundable `credits`
    to apply, plus `closing_tax_state` -- the engine's updated threaded tax state to
    carry forward as the next fiscal year's `opening_tax_state` (None for engines that
    thread no state) -- and `figures`, engine-specific derived figures (e.g. AGI/MAGI)
    for downstream consumers. `closing_tax_state` and `figures` are opaque to the Period
    and to this neutral module: their concrete types (e.g. the US `TaxState` /
    `TaxFigures`) live in the country package, so they are typed `object` here to keep
    the agnostic layer from depending on a specific jurisdiction."""

    charges           : list[ TaxCharge ] = field( default_factory = list )
    credits           : list[ TaxCredit ] = field( default_factory = list )
    closing_tax_state : object = None
    figures           : object = None


class TaxEngine:
    """A tax-calculation strategy. Subclasses implement `assess`; the tax-year calendar
    defaults to the civil year and is overridden by a jurisdiction on a different fiscal
    year. The Period owns one engine every interval and asks it when to settle, rather than
    being handed a pre-decided window -- the boundary is the tax law's to know."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        raise NotImplementedError

    def assess_penalties( self, candidates, tax_context ) -> list:
        """The `TaxPenalty`s incurred by this interval's money-movement `candidates` (e.g. the
        early-withdrawal penalty). Default: none. The engine owns the whole filter -- which
        candidates qualify and the rate -- so the Period need only report the movements."""
        return []

    def closes_tax_year( self, on_date : date ) -> bool:
        """Whether a tax year ends on `on_date` -- the interval on which the Period settles
        tax. Civil-year default: December 31."""
        return ( on_date.month == 12 ) and ( on_date.day == 31 )

    def tax_year_bounds( self, on_date : date ) -> tuple[ date, date ]:
        """The (start, end) dates of the tax year containing `on_date` -- the full span the
        engine assesses over. Civil-year default: January 1 to December 31 of that year."""
        return ( date( on_date.year, 1, 1 ), date( on_date.year, 12, 31 ) )


class ZeroTaxEngine( TaxEngine ):
    """Country-neutral stand-in that assesses no tax, so the Period flow can be
    exercised end to end before a real engine exists."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        return TaxAssessment()
