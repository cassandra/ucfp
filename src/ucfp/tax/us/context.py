"""The US taxpayer context -- the `tax_context` the US federal engine consumes.

US-shaped (filing status, the people on the return, later ACA/state), so it lives in
the US package. The Scenario resolves it per interval -- ages from birthdates, wages
from the period's income, filing status from post-event household state -- so a
forecast that crosses an age-65 or filing-status boundary picks up the change
automatically. A neutral taxpayer seam can be extracted if a second jurisdiction is
added.

NOTE: carries what the engine needs per individual. Income tax reads aggregate income
from the ledger (the `FiscalWindow`); per-subject facts that the ledger does not split
-- ages (deduction bonuses) and wages (FICA's per-worker Social Security cap) -- live
here. The Scenario keeps the subjects' wages consistent with the ledger's wage total.
Household size, state, ACA enrollment, and per-subject blindness join as the engine's
later stages land.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .enums import FilingStatus


@dataclass( frozen = True )
class TaxSubject:
    """One person on the tax return: the per-individual facts the engine needs --
    age (for the age-65 and senior deduction bonuses) and wages (for FICA, where each
    worker's Social Security tax is capped at the wage base separately)."""

    age   : int
    wages : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class TaxContext:
    """The resolved taxpayer facts for one fiscal window: the filing status and the
    people on the return."""

    filing_status : FilingStatus
    subjects      : tuple = field( default_factory = tuple )

    def count_age_at_least( self, age : int ) -> int:
        """How many subjects are at least `age` -- e.g. the 65+ count that drives the
        per-subject standard-deduction bonuses."""
        return sum( 1 for subject in self.subjects if subject.age >= age )
