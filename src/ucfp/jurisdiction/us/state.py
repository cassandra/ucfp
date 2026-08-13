"""The US federal engine's threaded tax state -- the `opening_tax_state` /
`closing_tax_state` carried fiscal-year to fiscal-year.

Carryforwards beyond a single year are not lost. A net capital loss beyond the year's
ordinary-income offset carries forward, preserving its short- vs long-term character.
Rental losses disallowed by the passive-activity rules are suspended and carried
forward. Those are the carryforwards threaded here; `TaxState` is the container the
engine reads and returns.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from ucfp.jurisdiction.engine import TaxState as NeutralTaxState


@dataclass( frozen = True )
class CapitalLossCarryover:
    """Unused capital losses carried into a fiscal year, by character. Both are
    non-negative loss magnitudes (zero when nothing carries)."""

    short : Decimal = Decimal( '0' )
    long  : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class PassiveLossCarryover:
    """Suspended passive-activity (rental) losses carried into a fiscal year -- a
    non-negative magnitude, aggregated across all rentals (not tracked per activity)."""

    suspended : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class TaxState( NeutralTaxState ):
    """The engine's threaded fiscal-year-to-fiscal-year tax state -- the US realization of the
    neutral `TaxState` marker. The empty default is the seed for a taxpayer with no prior
    carryforwards."""

    capital_loss_carryover : CapitalLossCarryover = field(
        default_factory = CapitalLossCarryover )
    passive_loss_carryover : PassiveLossCarryover = field(
        default_factory = PassiveLossCarryover )
    # The income tax assessed for the year this state closes -- read the next year as the prior-year
    # figure that caps the estimated-tax safe harbor. None until a first full year has been assessed.
    prior_year_income_tax : Optional[ Decimal ] = None
