"""Feature-neutral household facts gathered from the login-free tools, held in the session.

A visitor can use the calculators (e.g. the Social Security timing calculator) with no account, entering
facts about their household -- birth years, benefit amounts, an expected lifetime. `SessionFacts` holds
those facts in the session so a tool can re-prefill them on a return visit, and so a brand-new Profile can
be seeded from them once the visitor starts their own plan (see `ucfp.inputs.profile.repository`).

It is deliberately NOT the persisted `Profile`, and NOT a subset of it: it carries whatever a tool finds
useful (an expected lifetime has no Profile home yet) and, when it seeds a Profile, only ever fills facts
the Profile does not already carry. The mapping from these facts to Profile facts lives on the Profile
side, so this stays a neutral bag that no one feature owns.

The session is JSON-backed, so `to_storage` / `from_storage` round-trip through plain JSON types (Decimals
as strings), mirroring the other typed session slots (see `ucfp.session_state`).
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional


def _int_or_none( value ) -> Optional[ int ]:
    """A stored value coerced to int, or None when absent or malformed -- the safe read for a JSON-backed
    integer fact (tolerate a bad value rather than raise)."""
    try:
        return int( value )
    except ( TypeError, ValueError ):
        return None


def _decimal_or_none( value ) -> Optional[ Decimal ]:
    """A stored value as a Decimal, or None when absent or malformed -- money is stored as a string, so
    this parses it back tolerantly."""
    if value is None:
        return None
    try:
        return Decimal( str( value ) )
    except ( InvalidOperation, ValueError ):
        return None


@dataclass
class PersonFacts:
    """One household member's facts as entered into a tool. Every field is optional -- a tool records only
    what it asked. `government_pension_monthly` is the monthly state-pension benefit at the jurisdiction's
    normal retirement age (the US Social Security PIA at full retirement age); `life_expectancy` is an age
    (no Profile home yet -- carried for a tool's own re-prefill and for a future Profile fact). `sex`
    ('female'/'male'/None) and `longevity_setback` (years a person expects to differ from average lifespan,
    positive = shorter) are the two ways an actuarial estimate is tuned, carried the same neutral way."""

    birth_year                 : Optional[ int ]     = None
    government_pension_monthly : Optional[ Decimal ] = None
    life_expectancy            : Optional[ int ]     = None
    sex                        : Optional[ str ]     = None
    longevity_setback          : Optional[ int ]     = None

    def to_storage( self ) -> dict:
        """This person as a JSON-serializable dict (the monthly amount stringified)."""
        return {
            'birth_year'                 : self.birth_year,
            'government_pension_monthly' : ( None if self.government_pension_monthly is None
                                             else str( self.government_pension_monthly ) ),
            'life_expectancy'            : self.life_expectancy,
            'sex'                        : self.sex,
            'longevity_setback'          : self.longevity_setback }

    @staticmethod
    def from_storage( raw ) -> 'PersonFacts':
        """Rebuild a person from its stored dict, tolerating missing or malformed keys."""
        raw = raw or {}
        return PersonFacts(
            birth_year                 = _int_or_none( raw.get( 'birth_year' ) ),
            government_pension_monthly = _decimal_or_none( raw.get( 'government_pension_monthly' ) ),
            life_expectancy            = _int_or_none( raw.get( 'life_expectancy' ) ),
            sex                        = raw.get( 'sex' ) or None,
            longevity_setback          = _int_or_none( raw.get( 'longevity_setback' ) ) )


@dataclass
class SessionFacts:
    """The household a visitor has described to the tools, as an ordered list of people (the primary, then
    a partner). Empty when nothing has been entered. `is_couple` is simply whether a second person is
    present -- the tools record one person for a single household and two for a couple."""

    people : list[ PersonFacts ] = field( default_factory = list )

    @property
    def is_couple( self ) -> bool:
        return len( self.people ) >= 2

    def to_storage( self ) -> dict:
        """This slot as a JSON-serializable dict for the session."""
        return { 'people': [ person.to_storage() for person in self.people ] }

    @staticmethod
    def from_storage( raw ) -> 'SessionFacts':
        """Rebuild a slot from its stored dict, tolerating a missing or malformed people list."""
        raw = raw or {}
        return SessionFacts(
            people = [ PersonFacts.from_storage( person ) for person in raw.get( 'people' ) or [] ] )
