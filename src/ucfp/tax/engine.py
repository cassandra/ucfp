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
from decimal import Decimal

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
    """A tax-calculation strategy. Subclasses implement `assess`."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        raise NotImplementedError


class ZeroTaxEngine( TaxEngine ):
    """Country-neutral stand-in that assesses no tax, so the Period flow can be
    exercised end to end before a real engine exists."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        return TaxAssessment()
