"""The pluggable tax-calculation interface.

A `TaxEngine` is a black box to the Period: given the fiscal window's ledger facts,
the resolved `TaxContext`, and the opening tax attributes (carryovers), it returns
the charges to book, any credits, and the updated attributes. Tax parameters
(brackets, thresholds, schedules) are owned *inside* an engine -- never part of
this interface and never passed by the Scenario. Composition follows: federal +
state is a composite engine; another country is another engine; the Period and
Scenario never change.

`TaxContext` lives here, not in `forecast/`, because it is the engine's input
contract -- the dependency runs forecast -> tax.

NOTE: interface + a Phase-1 zero-tax stand-in. `USFederalTaxEngine` is Phase 2.
"""
from dataclasses import dataclass, field


@dataclass( frozen = True )
class TaxAssessment:
    """The result of `TaxEngine.assess`: the charges to book -- each an
    `(ExpenseTaxClass, amount)` the Period posts as a tax expense. Credits (e.g.
    ACA PTC) and updated carryover attributes come with the USFederalTaxEngine.
    """

    charges : list = field( default_factory = list )


class TaxContext:
    """The resolved taxpayer context for an interval -- the `tax_context` argument
    to `assess`: filing status, household size, state, ACA enrollment, and
    per-subject ages/blindness. The Scenario resolves it (the former "Profile"
    facts are time-varying personal parameters); `tax/` owns its shape because it
    is the engine's input contract.

    NOTE: stub -- fields TBD (needs filing-status / state enums).
    """


class TaxEngine:
    """A tax-calculation strategy. Subclasses implement `assess`."""

    def assess( self, fiscal_window, tax_context : TaxContext, opening_attrs ) -> TaxAssessment:
        raise NotImplementedError


class ZeroTaxEngine( TaxEngine ):
    """Phase-1 stand-in that assesses no tax, so the Period flow can be exercised
    end to end before `USFederalTaxEngine` exists."""

    def assess( self, fiscal_window, tax_context : TaxContext, opening_attrs ) -> TaxAssessment:
        return TaxAssessment()
