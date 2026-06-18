"""The US federal engine's threaded tax state -- the `opening_tax_state` /
`closing_tax_state` carried fiscal-year to fiscal-year.

A net capital loss beyond the year's ordinary-income offset is not lost: it carries
forward, preserving its short- vs long-term character, and nets against future gains
of the same character first. That carryover is the state threaded here. `TaxState`
is the container the engine reads and returns; today it holds only the capital-loss
carryover, but the wider carryforward family (passive-activity losses, AMT credit,
charitable) joins it as those stages land -- hence "placeholder".
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
class TaxState:
    """The engine's threaded fiscal-year-to-fiscal-year tax state. The empty default
    is the seed for a taxpayer with no prior carryforwards."""

    capital_loss_carryover : CapitalLossCarryover = field(
        default_factory = CapitalLossCarryover )
