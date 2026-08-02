"""Couple-aware realization of government (Social Security) retirement benefits.

Turns each household member's entitlement (PIA -- the full-retirement-age benefit) and claiming date
into their realized benefit schedule, applying the spousal benefit: when both are collecting, the
lower earner receives their own benefit plus a spousal top-up off the higher earner's record. A member
with no own entitlement in a couple is treated as a non-earning spouse -- a pure spousal benefit,
claimed on the earner's date (the earner must have filed for the benefit to exist, so an older
non-earning spouse cannot claim earlier and a younger one claims early rather than waiting for an age).

Pure and jurisdiction-neutral: the statutory amounts come from `GovernmentPension` (the US rules live
behind it), while the pairing, the both-collecting window, and the non-earning-spouse default are the
neutral orchestration here. Decoupled from `IncomeStream`, so the Social Security timing feature can
sweep claiming dates over it. Survivor benefits are not modeled.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.date_window import DateWindow
from common.schedule import Schedule

from ucfp.forecast.parameters import WindowedAmount
from ucfp.jurisdiction.government_pension import GovernmentPension


@dataclass( frozen = True )
class GovernmentPensionMember:
    """One household member's Social Security facts for realization: their `birthdate`, their entered
    PIA (`pia_monthly`, the full-retirement-age benefit) and `claiming_date` -- or None for each when
    not entered (a non-earning spouse). `subject_handle` keys the result back to the subject."""

    subject_handle : str
    birthdate      : date
    pia_monthly    : Optional[ Decimal ] = None
    claiming_date  : Optional[ date ]    = None


@dataclass( frozen = True )
class RealizedGovernmentPension:
    """A member's realized Social Security benefit: the amount schedule (today's dollars, stepping up
    where the spousal top-up begins) and `start_date`, the window start (their claiming date)."""

    subject_handle : str
    start_date     : date
    amounts        : Schedule


@dataclass( frozen = True )
class _ActiveClaim:
    """A member resolved to an active claim -- PIA and claiming date both known (a real entitlement,
    or a synthesized non-earning spouse at zero PIA claiming on the earner's date)."""

    subject_handle : str
    birthdate      : date
    pia_monthly    : Decimal
    claiming_date  : date


def realized_government_pensions(
        members : list[ GovernmentPensionMember ],
        government_pension : GovernmentPension ) -> list[ RealizedGovernmentPension ]:
    """Each member's realized Social Security benefit, with the spousal top-up applied for a couple.
    A member with no entered entitlement yields no benefit -- EXCEPT a non-earning spouse in a couple
    whose partner has one, who receives a pure spousal benefit claimed on the earner's date. A single
    member (or a lone earner) gets only their own benefit."""
    active = _active_claims( members )
    if not active:
        return list()
    if len( active ) == 1:
        return [ _own_only( active[ 0 ], government_pension ) ]
    if len( active ) == 2:
        return _couple( active, government_pension )
    raise ValueError(
        'Government pension realization models a household of at most two members (a couple); '
        f'got {len( active )} entitled members.' )


def _active_claims( members : list[ GovernmentPensionMember ] ) -> list[ _ActiveClaim ]:
    """Resolve members to active claims. A member with a PIA is active as entered (an entitled member
    missing a claiming date is an error). When a couple has exactly one entitled member, the other is
    synthesized as a non-earning spouse."""
    entitled = [ member for member in members if member.pia_monthly is not None ]
    if not entitled:
        return list()
    for member in entitled:
        if member.claiming_date is None:
            raise ValueError(
                f'The government pension for "{member.subject_handle}" needs a claiming date in the '
                'plans timing.' )
    active = [ _ActiveClaim(
        subject_handle = member.subject_handle, birthdate = member.birthdate,
        pia_monthly = member.pia_monthly, claiming_date = member.claiming_date )
        for member in entitled ]
    spouse = _non_earning_spouse_claim( entitled, members )
    if spouse is not None:
        active.append( spouse )
    return active


def _non_earning_spouse_claim(
        entitled : list[ GovernmentPensionMember ],
        members : list[ GovernmentPensionMember ] ) -> Optional[ _ActiveClaim ]:
    """The non-earning-spouse claim for a couple where exactly one member is entitled: the other member
    at zero PIA claiming on the earner's date -- a pure spousal benefit, which cannot begin before the
    earner has filed. None when both (or neither) are entitled, or there is no partner."""
    if len( members ) != 2 or len( entitled ) != 1:
        return None
    earner = entitled[ 0 ]
    spouse = next( member for member in members
                   if member.subject_handle != earner.subject_handle )
    return _ActiveClaim(
        subject_handle = spouse.subject_handle, birthdate = spouse.birthdate,
        pia_monthly = Decimal( 0 ), claiming_date = earner.claiming_date )


def _own_only(
        claim : _ActiveClaim, government_pension : GovernmentPension ) -> RealizedGovernmentPension:
    """A member's own benefit as a constant schedule from their claiming date -- no spousal top-up."""
    own = government_pension.realized_annual_benefit(
        claim.pia_monthly, claim.birthdate, claim.claiming_date )
    return RealizedGovernmentPension(
        subject_handle = claim.subject_handle, start_date = claim.claiming_date,
        amounts = Schedule.constant(
            WindowedAmount( own, DateWindow( start = claim.claiming_date ) ) ) )


def _couple(
        active : list[ _ActiveClaim ],
        government_pension : GovernmentPension ) -> list[ RealizedGovernmentPension ]:
    """Both members realized: the higher earner gets their own benefit; the lower earner gets their
    own plus the spousal excess once both are collecting."""
    higher, lower = sorted( active, key = lambda claim : claim.pia_monthly, reverse = True )
    excess = government_pension.spousal_excess_annual_benefit(
        higher.pia_monthly, lower.pia_monthly, lower.birthdate, lower.claiming_date )
    return [
        _own_only( higher, government_pension ),
        _lower_with_spousal( lower, higher.claiming_date, excess, government_pension ),
    ]


def _lower_with_spousal(
        lower : _ActiveClaim, higher_claiming : date, excess : Decimal,
        government_pension : GovernmentPension ) -> RealizedGovernmentPension:
    """The lower earner's schedule: their own benefit, stepping up by the spousal `excess` once both
    are collecting (the later of the two claiming dates). No excess (own already meets half the higher
    PIA) leaves a plain own-benefit schedule; a higher earner who claims first collapses it to one
    already-topped-up segment."""
    own = government_pension.realized_annual_benefit(
        lower.pia_monthly, lower.birthdate, lower.claiming_date )
    both_collecting = max( lower.claiming_date, higher_claiming )
    if excess <= 0 or both_collecting <= lower.claiming_date:
        amount   = own if excess <= 0 else own + excess
        segments = ( WindowedAmount( amount, DateWindow( start = lower.claiming_date ) ), )
    else:
        segments = (
            WindowedAmount( own, DateWindow(
                start = lower.claiming_date, end = both_collecting - timedelta( days = 1 ) ) ),
            WindowedAmount( own + excess, DateWindow( start = both_collecting ) ) )
    return RealizedGovernmentPension(
        subject_handle = lower.subject_handle, start_date = lower.claiming_date,
        amounts = Schedule( segments ) )
