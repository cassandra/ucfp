"""The pluggable, country-agnostic tax interface.

A `TaxEngine` is a black box to the Period: given the fiscal window's ledger facts,
the resolved taxpayer context, and the opening tax attributes (carryovers), it
returns the charges to book, any credits, and the updated attributes. Everything
jurisdiction-specific -- the taxpayer-context shape, parameters, brackets, rules --
lives in a country package (e.g. `tax/us/`); this module stays neutral. The
`tax_context` passed to `assess` is therefore engine-specific.
"""
from dataclasses import dataclass, field


@dataclass( frozen = True )
class TaxAssessment:
    """The result of `TaxEngine.assess`: the charges to book -- each an
    `(ExpenseTaxClass, amount)` the Period posts as a tax expense. Credits (e.g.
    ACA PTC) and updated carryover attributes come with a real engine."""

    charges : list = field( default_factory = list )


class TaxEngine:
    """A tax-calculation strategy. Subclasses implement `assess`."""

    def assess( self, fiscal_window, tax_context, opening_attrs ) -> TaxAssessment:
        raise NotImplementedError


class ZeroTaxEngine( TaxEngine ):
    """Country-neutral stand-in that assesses no tax, so the Period flow can be
    exercised end to end before a real engine exists."""

    def assess( self, fiscal_window, tax_context, opening_attrs ) -> TaxAssessment:
        return TaxAssessment()
