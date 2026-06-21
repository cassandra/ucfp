"""US filing-status resolution over time -- the survivor (qualifying-surviving-spouse) rule.

When a spouse dies, the survivor's filing status is not a simple immediate flip: the year of
death may still be filed jointly, and the two following years qualify for surviving-spouse
treatment, which uses the same brackets and standard deduction as married-filing-jointly --
so it is modeled here *as* MARRIED_JOINT (no separate enum value needed). Only after that does
the survivor file SINGLE. This rule is US tax law, so it lives in tax/us; the engine applies
`resolve_filing_status` per year from the standing status and death year the Forecast supplies,
and the Forecast never encodes the rule itself.
"""
from typing import Optional

from ucfp.tax.enums import FilingStatus


def resolve_filing_status(
        base_status : FilingStatus,
        death_year  : Optional[ int ],
        target_year : int ) -> FilingStatus:
    """The filing status in `target_year` given the household's `base_status` and the year a
    spouse died (`death_year`, or None for no death). A non-joint base is unaffected (a single
    filer stays single). For a joint base: the death year and the next two years file as
    MARRIED_JOINT (the year-of-death joint return, then the two surviving-spouse years), and
    SINGLE thereafter. The surviving-spouse dependent-child requirement is not checked --
    surviving-spouse treatment is always granted."""
    if ( death_year is None ) or ( target_year <= death_year ):
        return base_status
    if base_status != FilingStatus.MARRIED_JOINT:
        return base_status
    if target_year <= death_year + 2:
        return FilingStatus.MARRIED_JOINT
    return FilingStatus.SINGLE
