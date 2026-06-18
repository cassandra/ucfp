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


@dataclass( frozen = True )
class TaxAssessment:
    """The result of `TaxEngine.assess`: the charges to book -- each an
    `(ExpenseTaxClass, amount)` the Period posts as a tax expense -- and
    `closing_tax_state`, the engine's updated threaded tax state (opaque to the
    Period) to carry forward as the next fiscal year's `opening_tax_state`. It is
    None for engines that thread no state. `figures` holds engine-specific derived
    figures (e.g. AGI/MAGI) for downstream consumers, also opaque to the Period.
    `credits` are refundable credits -- each an `(ExpenseTaxClass, amount)` the Period
    books against that tax (e.g. the ACA premium tax credit against income tax),
    refundable so the net settlement may be a refund."""

    charges           : list = field( default_factory = list )
    closing_tax_state : object = None
    figures           : object = None
    credits           : list = field( default_factory = list )


class TaxEngine:
    """A tax-calculation strategy. Subclasses implement `assess`."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        raise NotImplementedError


class ZeroTaxEngine( TaxEngine ):
    """Country-neutral stand-in that assesses no tax, so the Period flow can be
    exercised end to end before a real engine exists."""

    def assess( self, fiscal_window, tax_context, opening_tax_state ) -> TaxAssessment:
        return TaxAssessment()
