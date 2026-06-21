"""The US taxpayer context -- the `tax_context` the US federal engine consumes.

US-shaped (filing status, the people on the return, later ACA/state), so it lives in
the US package. The Scenario resolves it per interval -- ages from birthdates, wages
from the period's income, filing status from post-event household state -- so a
forecast that crosses an age-65 or filing-status boundary picks up the change
automatically. A neutral taxpayer seam can be extracted if a second jurisdiction is
added.

Carries the per-individual facts the engine needs that are NOT money amounts in the ledger:
the engine reads all income (including per-worker wages, since each worker has their own
WAGES account) from the ledger via the `FiscalWindow`; what lives here is non-monetary
per-subject status -- ages (deduction bonuses).
"""
from dataclasses import dataclass, field
from typing import Optional

from ucfp.accounts.schemas import Handle
from ucfp.tax.subsidized_health import SubsidizedHealthEnrollment

from .enums import FilingStatus
from .property import TaxProperty


@dataclass( frozen = True )
class TaxSubject:
    """One person on the tax return: the per-individual facts the engine needs that are not
    amounts in the ledger -- the age (for the age-65/senior deduction bonuses and the 59-1/2
    threshold), the `birth_year` (for the SECURE 2.0 RMD-start cohort), and the `handle` that
    pairs them with their owned accounts (so an account-attributed rule like the
    early-withdrawal penalty or RMD can reach this person's age), None when the subject owns no
    handled account. Blindness (another additional-standard-deduction trigger) will join it."""

    age        : int
    birth_year : int
    handle     : Optional[ Handle ] = None


@dataclass( frozen = True )
class TaxContext:
    """The resolved taxpayer facts for one fiscal window: the filing status, the people
    on the return (`subjects`), the real estate held (`properties`, for §121/§1250 at
    sale and rental depreciation), subsidized health-coverage enrollment (`health_enrollment`,
    None when not enrolled, which the US engine turns into the ACA premium tax credit), and
    whether the taxpayer actively participates in rentals.

    `rental_active_participation` is a single household-level flag: the passive-activity
    rules treat all rentals as one activity with uniform participation. Supporting a MIX of
    active and passive rentals requires per-property rental accounts and per-activity netting
    -- the Scenario must therefore not create non-actively-participated rentals while this flag
    governs them all."""

    filing_status     : FilingStatus
    subjects          : tuple[ TaxSubject, ... ]  = field( default_factory = tuple )
    properties        : tuple[ TaxProperty, ... ] = field( default_factory = tuple )
    health_enrollment : Optional[ SubsidizedHealthEnrollment ] = None
    rental_active_participation : bool = True

    def count_age_at_least( self, age : int ) -> int:
        """How many subjects are at least `age` -- e.g. the 65+ count that drives the
        per-subject standard-deduction bonuses."""
        return sum( 1 for subject in self.subjects if subject.age >= age )

    def subject_for( self, handle : Handle ) -> Optional[ TaxSubject ]:
        """The subject identified by `handle` (the owner of an account carrying it), or None
        -- used to reach an account owner's age for an account-attributed rule. Handles are
        compared by their string (their identity), so any planner scheme works."""
        target = str( handle )
        for subject in self.subjects:
            if ( subject.handle is not None ) and ( str( subject.handle ) == target ):
                return subject
        return None
