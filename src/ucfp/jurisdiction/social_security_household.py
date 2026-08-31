"""Couple-aware Social Security benefit for a household on a date -- the per-period statutory calculation
the forecast engine invokes each interval.

Given each member's entitlement (PIA -- the full-retirement-age benefit -- and claiming date), it returns
their Social Security benefit on a date: their own claim-adjusted benefit once they have claimed, plus the
lower earner's spousal top-up once *both* are collecting. A member with no own entitlement in a couple is a
non-earning spouse -- a pure spousal benefit that cannot begin before the earner has filed.

Pure and jurisdiction-neutral: statutory amounts come from `GovernmentPension` (the US rules behind it),
while the pairing, the both-collecting rule, and the non-earning-spouse default are the neutral orchestration
here. The engine calls this per interval -- applying the COLA and the funding-shortfall reduction over the
result, and owning the timing -- so no schedules are built here; the benefit is a today's-dollars amount on a
date. On a death (from a member's `death_date`) the survivor receives the larger of their own and the
decedent's own benefit, and the decedent's own + spousal end -- the survivor transition.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.jurisdiction.government_pension import GovernmentPension


@dataclass( frozen = True )
class HouseholdMember:
    """One member's Social Security facts: their `birthdate`, entered PIA (`pia_monthly`, the benefit at
    full retirement age) and `claiming_date` -- or None for each when not entered (a non-earning spouse) --
    and their `death_date` when known (from the expected lifetime), which drives the survivor transition.
    `subject_handle` keys the benefit back to the subject."""

    subject_handle : str
    birthdate      : date
    pia_monthly    : Optional[ Decimal ] = None
    claiming_date  : Optional[ date ]    = None
    death_date     : Optional[ date ]    = None


@dataclass( frozen = True )
class _Claim:
    """A member resolved to an active claim -- PIA and claiming date both known (a real entitlement, or a
    synthesized non-earning spouse at zero PIA claiming on the earner's date)."""

    subject_handle : str
    birthdate      : date
    pia_monthly    : Decimal
    claiming_date  : date
    death_date     : Optional[ date ] = None


def household_benefits(
        members : list[ HouseholdMember ], government_pension : GovernmentPension,
        on_date : date ) -> dict[ str, Decimal ]:
    """Each member's annual Social Security benefit (today's dollars) on `on_date`, keyed by
    `subject_handle`: their own claim-adjusted benefit once they have claimed, plus -- for the lower earner
    of a couple -- the spousal top-up once both are collecting. After the first death the survivor receives
    the larger of their own and the decedent's own benefit (spousal top-ups end); a member is gone the year
    after their death. Not-yet-collecting is 0; a member with no entitlement yields no benefit, except a
    non-earning spouse in a couple whose partner has one."""
    active = _active_claims( members )
    benefits = { claim.subject_handle: Decimal( 0 ) for claim in active }
    if len( active ) == 1:
        if not _has_died( active[ 0 ], on_date ):
            benefits[ active[ 0 ].subject_handle ] = _own_benefit( active[ 0 ], government_pension, on_date )
        return benefits
    if len( active ) == 2:
        higher, lower = sorted( active, key = lambda claim: claim.pia_monthly, reverse = True )
        if _has_died( higher, on_date ) and not _has_died( lower, on_date ):
            benefits[ lower.subject_handle ] = _survivor_benefit( lower, higher, government_pension, on_date )
        elif _has_died( lower, on_date ) and not _has_died( higher, on_date ):
            benefits[ higher.subject_handle ] = _survivor_benefit( higher, lower, government_pension, on_date )
        elif not _has_died( higher, on_date ) and not _has_died( lower, on_date ):
            benefits[ higher.subject_handle ] = _own_benefit( higher, government_pension, on_date )
            benefits[ lower.subject_handle ]  = _lower_benefit( lower, higher, government_pension, on_date )
        # both gone: no benefit (the plan has ended).
    return benefits


def _has_died( claim : _Claim, on_date : date ) -> bool:
    """Whether the member has died as of `on_date` -- gone the year after the death, matching the engine's
    other removal transitions (household size, account retitling)."""
    return claim.death_date is not None and on_date.year > claim.death_date.year


def _survivor_benefit(
        survivor : _Claim, decedent : _Claim, government_pension : GovernmentPension,
        on_date : date ) -> Decimal:
    """The survivor's benefit after the first death: the larger of their own claim-adjusted benefit (once
    they have claimed) and the decedent's own claim-adjusted benefit -- so delaying the higher earner buys a
    larger survivor benefit. Spousal top-ups end; a non-earning decedent (zero PIA) leaves the survivor's own."""
    survivor_own = _own_benefit( survivor, government_pension, on_date )
    decedent_own = government_pension.realized_annual_benefit(
        decedent.pia_monthly, decedent.birthdate, decedent.claiming_date )
    return max( survivor_own, decedent_own )


def _own_benefit( claim : _Claim, government_pension : GovernmentPension, on_date : date ) -> Decimal:
    """The member's own claim-adjusted annual benefit once they have claimed, else 0."""
    if on_date < claim.claiming_date:
        return Decimal( 0 )
    return government_pension.realized_annual_benefit(
        claim.pia_monthly, claim.birthdate, claim.claiming_date )


def _lower_benefit(
        lower : _Claim, higher : _Claim, government_pension : GovernmentPension, on_date : date ) -> Decimal:
    """The lower earner's benefit: their own once claimed, plus the spousal excess once both are collecting
    (the later of the two claiming dates). The excess floors at zero (own already meets half the higher)."""
    own = _own_benefit( lower, government_pension, on_date )
    excess = government_pension.spousal_excess_annual_benefit(
        higher.pia_monthly, lower.pia_monthly, lower.birthdate, lower.claiming_date )
    both_collecting = max( lower.claiming_date, higher.claiming_date )
    if excess > 0 and on_date >= both_collecting:
        return own + excess
    return own


def _active_claims( members : list[ HouseholdMember ] ) -> list[ _Claim ]:
    """Members resolved to active claims: each entitled member (a PIA needs a claiming date), plus a
    synthesized non-earning spouse (zero PIA on the earner's date) when a couple has exactly one entitled
    member. A household is at most two members (a couple)."""
    entitled = [ member for member in members if member.pia_monthly is not None ]
    if not entitled:
        return list()
    for member in entitled:
        if member.claiming_date is None:
            raise ValueError(
                f'The Social Security entitlement for "{member.subject_handle}" needs a claiming date.' )
    claims = [ _Claim( member.subject_handle, member.birthdate, member.pia_monthly, member.claiming_date,
                       member.death_date )
               for member in entitled ]
    spouse = _non_earning_spouse( entitled, members )
    if spouse is not None:
        claims.append( spouse )
    if len( claims ) > 2:
        raise ValueError(
            f'Social Security models a household of at most two members (a couple); got {len( claims )}.' )
    return claims


def _non_earning_spouse(
        entitled : list[ HouseholdMember ], members : list[ HouseholdMember ] ) -> Optional[ _Claim ]:
    """The non-earning-spouse claim for a couple where exactly one member is entitled: the other at zero PIA
    claiming on the earner's date (a pure spousal benefit, which cannot begin before the earner files). None
    when both (or neither) are entitled, or there is no partner."""
    if len( members ) != 2 or len( entitled ) != 1:
        return None
    earner = entitled[ 0 ]
    spouse = next( member for member in members if member.subject_handle != earner.subject_handle )
    return _Claim( spouse.subject_handle, spouse.birthdate, Decimal( 0 ), earner.claiming_date,
                   spouse.death_date )
