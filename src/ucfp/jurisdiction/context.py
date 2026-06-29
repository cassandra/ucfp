"""The taxpayer context -- the `tax_context` a jurisdiction's engine consumes.

The Forecast resolves it per interval (ages from birthdates, the people on the return, the
real estate held, health-coverage enrollment) and states facts only: it carries the
household's *standing* `filing_status` and the year a filing spouse died, and the engine
applies its own jurisdiction's rules (e.g. a surviving-spouse transition) to derive the
effective status. This is general -- a country's engine reads what it needs and ignores the
rest. The engine reads all *money* (including per-worker wages) from the ledger via the
`FiscalWindow`; only non-monetary per-subject status lives here -- ages (deduction bonuses).
"""
from dataclasses import dataclass, field
from typing import Optional

from ucfp.accounts.schemas import Handle
from ucfp.jurisdiction.subsidized_health import SubsidizedHealthEnrollment

from .enums import FilingStatus
from .property import TaxProperty


@dataclass( frozen = True )
class TaxSubject:
    """One person on the tax return: the per-individual facts the engine needs that are not
    amounts in the ledger -- the age (for age-65/senior deduction bonuses and the 59-1/2
    threshold), the `birth_year` (for the RMD-start cohort), and the `handle` that pairs them
    with their owned accounts (so an account-attributed rule like the early-withdrawal penalty
    or RMD can reach this person's age), None when the subject owns no handled account."""

    age        : int
    birth_year : int
    handle     : Optional[ Handle ] = None


@dataclass( frozen = True )
class TaxContext:
    """The resolved taxpayer facts for one fiscal window: the household's standing
    `filing_status`, the year a filing spouse died (`spouse_death_year`, driving any
    surviving-spouse transition the engine applies), the people on the return (`subjects`),
    the real estate held (`properties`, for gain-exclusion/recapture at sale and rental
    depreciation), health-coverage enrollment (`health_enrollment`, None when not enrolled),
    and whether the taxpayer actively participates in rentals.

    `rental_active_participation` is a single household-level flag: the passive-activity
    rules treat all rentals as one activity with uniform participation. Supporting a MIX of
    active and passive rentals requires per-property rental accounts and per-activity netting
    -- the Scenario must therefore not create non-actively-participated rentals while this flag
    governs them all."""

    filing_status     : FilingStatus
    spouse_death_year : Optional[ int ]           = None
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
