"""Jurisdiction-local terminology for neutral domain concepts.

Some concepts carry a jurisdiction-specific everyday name -- a government pension is "Social Security"
in the US, a tax-free retirement account is a "Roth". The neutral name is the concept's own label
(`JurisdictionConcept`); this module resolves the *local* term for a jurisdiction, so the UI can show
"Pre-tax retirement (401(k) / IRA)" without any US string leaking into a template or form. It is the
one place that maps a `JurisdictionType` to its local vocabulary.
"""
from typing import Optional

from .enums import JurisdictionConcept, JurisdictionType
from .us.labels import US_LOCAL_TERMS


_LOCAL_TERMS = {
    JurisdictionType.US_FEDERAL : US_LOCAL_TERMS,
}


def local_term( jurisdiction_type : JurisdictionType,
                concept : JurisdictionConcept ) -> Optional[ str ]:
    """The jurisdiction's local name for `concept` (e.g. 'Roth'), or None when it has no term distinct
    from the concept's neutral label."""
    return _LOCAL_TERMS.get( jurisdiction_type, {} ).get( concept )


def local_label( jurisdiction_type : JurisdictionType, concept : JurisdictionConcept ) -> str:
    """The concept's neutral name with the jurisdiction's local term in parentheses -- e.g. 'Pre-tax
    retirement (401(k) / IRA)' -- or just the neutral name when there is no distinct local term."""
    term = local_term( jurisdiction_type, concept )
    return f'{concept.label} ({term})' if term else concept.label
