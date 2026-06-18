"""The US taxpayer context -- the `tax_context` the US federal engine consumes.

US-shaped (filing status, subject ages, later ACA/state), so it lives in the US
package. The Scenario resolves it per interval -- ages from birthdates, filing
status from post-event household state -- so a forecast that crosses an age-65 or
filing-status boundary picks up the change automatically. A neutral taxpayer seam
can be extracted if a second jurisdiction is added.

NOTE: carries what the income-tax core needs (filing status drives bracket/
deduction/SS-threshold selection; ages drive the age-65 and senior deduction
bonuses). Household size, state, ACA enrollment, and per-subject blindness are added
as the engine's later stages land.
"""
from dataclasses import dataclass, field

from .enums import FilingStatus


@dataclass( frozen = True )
class TaxContext:
    """The resolved taxpayer facts for one fiscal window. `subject_ages` are the
    ages of the taxpayer subjects during that window (one entry per person on the
    return), from which the engine counts those who qualify for the 65+ bonuses."""

    filing_status : FilingStatus
    subject_ages  : tuple = field( default_factory = tuple )

    def count_age_at_least( self, age : int ) -> int:
        """How many subjects are at least `age` -- e.g. the 65+ count that drives the
        per-subject standard-deduction bonuses."""
        return sum( 1 for subject_age in self.subject_ages if subject_age >= age )
