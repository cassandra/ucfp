"""The US taxpayer context -- the `tax_context` the US federal engine consumes.

US-shaped (filing status, the people on the return, later ACA/state), so it lives in
the US package. The Scenario resolves it per interval -- ages from birthdates, wages
from the period's income, filing status from post-event household state -- so a
forecast that crosses an age-65 or filing-status boundary picks up the change
automatically. A neutral taxpayer seam can be extracted if a second jurisdiction is
added.

NOTE: carries the per-individual facts the engine needs that are NOT money amounts in
the ledger. The engine reads all income (including per-worker wages, since each worker
has their own WAGES account) from the ledger via the `FiscalWindow`; what lives here is
non-monetary per-subject status -- currently ages (deduction bonuses). Household size,
state, ACA enrollment, and per-subject blindness join as the engine's later stages
land.
"""
from dataclasses import dataclass, field

from .enums import FilingStatus


@dataclass( frozen = True )
class TaxSubject:
    """One person on the tax return: the per-individual facts the engine needs that
    are not amounts in the ledger. Currently the age (for the age-65 and senior
    deduction bonuses); blindness (another additional-standard-deduction trigger) will
    join it."""

    age : int


@dataclass( frozen = True )
class TaxContext:
    """The resolved taxpayer facts for one fiscal window: the filing status, the people
    on the return (`subjects`), and the real estate held (`properties`, for §121/§1250
    at sale and rental depreciation)."""

    filing_status : FilingStatus
    subjects      : tuple = field( default_factory = tuple )
    properties    : tuple = field( default_factory = tuple )

    def count_age_at_least( self, age : int ) -> int:
        """How many subjects are at least `age` -- e.g. the 65+ count that drives the
        per-subject standard-deduction bonuses."""
        return sum( 1 for subject in self.subjects if subject.age >= age )
