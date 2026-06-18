"""The US federal engine's threaded tax state -- the `opening_tax_state` /
`closing_tax_state` carried fiscal-year to fiscal-year.

Carryforwards beyond a single year are not lost. A net capital loss beyond the year's
ordinary-income offset carries forward, preserving its short- vs long-term character.
Rental losses disallowed by the passive-activity rules are suspended and carried
forward. Those are the carryforwards threaded here; `TaxState` is the container the
engine reads and returns, and the wider family (AMT credit, charitable) joins it as
those stages land.
"""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass( frozen = True )
class CapitalLossCarryover:
    """Unused capital losses carried into a fiscal year, by character. Both are
    non-negative loss magnitudes (zero when nothing carries)."""

    short : Decimal = Decimal( '0' )
    long  : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class PassiveLossCarryover:
    """Suspended passive-activity (rental) losses carried into a fiscal year -- a
    non-negative magnitude. Aggregate for now; a per-activity breakdown (needed to
    release a property's suspended losses precisely at its disposition) can join later."""

    suspended : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class TaxState:
    """The engine's threaded fiscal-year-to-fiscal-year tax state. The empty default
    is the seed for a taxpayer with no prior carryforwards."""

    capital_loss_carryover : CapitalLossCarryover = field(
        default_factory = CapitalLossCarryover )
    passive_loss_carryover : PassiveLossCarryover = field(
        default_factory = PassiveLossCarryover )
