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

`household_benefit_breakdown` returns each member's benefit split into its own / spousal / survivor parts (a
per-person view the claiming calculator uses); `household_benefits` is the per-member totals the engine books.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from common.datetime_utils import add_years

from ucfp.jurisdiction.government_pension import GovernmentPension

# The earliest age a spousal benefit can be claimed. A non-earning spouse claims when the earner files, but
# never before this -- a spousal benefit is not payable before age 62, even if the earner filed earlier.
_EARLIEST_SPOUSAL_CLAIM_AGE = 62


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


@dataclass( frozen = True )
class MemberBenefit:
    """One member's annual Social Security on a date, split into its statutory parts (today's dollars): the
    member's own claim-adjusted benefit, the lower earner's spousal excess once both collect, and the
    survivor benefit after the other's death. Either the own(+spousal) pair or the survivor is non-zero,
    never both -- the survivor benefit replaces own and spousal at the first death."""

    own      : Decimal = Decimal( '0' )
    spousal  : Decimal = Decimal( '0' )
    survivor : Decimal = Decimal( '0' )

    @property
    def total( self ) -> Decimal:
        """What the member actually receives that year -- the sum of the parts."""
        return self.own + self.spousal + self.survivor


def household_benefit_breakdown(
        members : list[ HouseholdMember ], government_pension : GovernmentPension,
        on_date : date ) -> dict[ str, MemberBenefit ]:
    """Each member's annual Social Security on `on_date` (today's dollars), keyed by `subject_handle` and
    split into own / spousal / survivor parts -- the couple logic exposed for a per-person view. Own is the
    claim-adjusted benefit once claimed; the lower earner adds the spousal excess once both collect; after
    the first death the survivor's parts are replaced by the survivor benefit (the larger of the two own
    benefits), and a member is gone the year after their death. A member not yet collecting has empty parts;
    a member with no entitlement yields none, except a non-earning spouse in a couple whose partner has one.
    `household_benefits` is the per-member totals of this."""
    active = _active_claims( members )
    breakdown = { claim.subject_handle: MemberBenefit() for claim in active }
    if len( active ) == 1:
        solo = active[ 0 ]
        if not _has_died( solo, on_date ):
            breakdown[ solo.subject_handle ] = MemberBenefit(
                own = _own_benefit( solo, government_pension, on_date ) )
        return breakdown
    if len( active ) == 2:
        higher, lower = sorted( active, key = lambda claim: claim.pia_monthly, reverse = True )
        higher_dead, lower_dead = _has_died( higher, on_date ), _has_died( lower, on_date )
        if higher_dead and not lower_dead:
            breakdown[ lower.subject_handle ] = MemberBenefit(
                survivor = _survivor_benefit( lower, higher, government_pension, on_date ) )
        elif lower_dead and not higher_dead:
            breakdown[ higher.subject_handle ] = MemberBenefit(
                survivor = _survivor_benefit( higher, lower, government_pension, on_date ) )
        elif not higher_dead and not lower_dead:
            breakdown[ higher.subject_handle ] = MemberBenefit(
                own = _own_benefit( higher, government_pension, on_date ) )
            breakdown[ lower.subject_handle ] = MemberBenefit(
                own     = _own_benefit( lower, government_pension, on_date ),
                spousal = _spousal_excess( lower, higher, government_pension, on_date ) )
        # both gone: no benefit (the plan has ended).
    return breakdown


def household_benefits(
        members : list[ HouseholdMember ], government_pension : GovernmentPension,
        on_date : date ) -> dict[ str, Decimal ]:
    """Each member's total annual Social Security benefit (today's dollars) on `on_date`, keyed by
    `subject_handle` -- the sum of their own, spousal, and survivor parts (see
    `household_benefit_breakdown`). The forecast engine books this per interval; the calculator's
    per-person view reads the breakdown instead."""
    return { handle: benefit.total
             for handle, benefit in household_benefit_breakdown(
                 members, government_pension, on_date ).items() }


def _has_died( claim : _Claim, on_date : date ) -> bool:
    """Whether the member has died as of `on_date` -- gone the year after the death, matching the engine's
    other removal transitions (household size, account retitling)."""
    return claim.death_date is not None and on_date.year > claim.death_date.year


def _survivor_benefit(
        survivor : _Claim, decedent : _Claim, government_pension : GovernmentPension,
        on_date : date ) -> Decimal:
    """The survivor's benefit after the first death: the larger of their own claim-adjusted benefit and the
    decedent's -- each counted only once that person has (or would have) claimed -- so delaying the higher
    earner buys a larger survivor benefit. Spousal top-ups end; a non-earning decedent (zero PIA) leaves the
    survivor's own.

    The decedent's side is gated on the decedent's own claiming date, not just the date of death: the
    survivor inherits the benefit stream the decedent would have been collecting, which does not begin
    before the decedent's claim age. This matters only when death precedes that claim age (a young death, or
    the survival-state runs the SS timing calculator places at the horizon start) -- otherwise the survivor
    transition already falls after both claim dates."""
    survivor_own = _own_benefit( survivor, government_pension, on_date )
    decedent_own = _own_benefit( decedent, government_pension, on_date )
    return max( survivor_own, decedent_own )


def _own_benefit( claim : _Claim, government_pension : GovernmentPension, on_date : date ) -> Decimal:
    """The member's own claim-adjusted annual benefit once they have claimed, else 0."""
    if on_date < claim.claiming_date:
        return Decimal( 0 )
    return government_pension.realized_annual_benefit(
        claim.pia_monthly, claim.birthdate, claim.claiming_date )


def _spousal_excess(
        lower : _Claim, higher : _Claim, government_pension : GovernmentPension, on_date : date ) -> Decimal:
    """The lower earner's spousal top-up -- the excess over their own benefit -- once both are collecting
    (the later of the two claiming dates), else 0. Floors at zero when their own already meets half the
    higher earner's."""
    excess = government_pension.spousal_excess_annual_benefit(
        higher.pia_monthly, lower.pia_monthly, lower.birthdate, lower.claiming_date )
    both_collecting = max( lower.claiming_date, higher.claiming_date )
    if excess > 0 and on_date >= both_collecting:
        return excess
    return Decimal( 0 )


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
    claiming a pure spousal benefit. That benefit cannot begin before the earner files, nor before the
    spouse reaches age 62 (a spousal benefit is not payable earlier) -- so it starts on the later of the
    two, which matters when the earner files while the spouse is still under 62. None when both (or neither)
    are entitled, or there is no partner."""
    if len( members ) != 2 or len( entitled ) != 1:
        return None
    earner           = entitled[ 0 ]
    spouse           = next( member for member in members if member.subject_handle != earner.subject_handle )
    earliest_spousal = add_years( spouse.birthdate, _EARLIEST_SPOUSAL_CLAIM_AGE )
    claiming_date    = max( earner.claiming_date, earliest_spousal )
    return _Claim( spouse.subject_handle, spouse.birthdate, Decimal( 0 ), claiming_date,
                   spouse.death_date )
