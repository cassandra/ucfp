"""Social Security retirement-benefit adjustment for claiming date (US).

A standalone `jurisdiction/us` helper the planning layer calls to turn a subject's PIA (primary
insurance amount -- the monthly benefit at full retirement age) into the realized benefit for
a chosen claiming date. The SSA schedule adjusts the benefit by the month: it reduces the
benefit for each month claimed before full retirement age (FRA) and adds delayed-retirement
credits for each month after, up to age 70; FRA slides with birth year (65 for 1937 and
earlier, to 67 for 1960 and later). Benefits are in today's dollars; the engine grows them by
the Social Security COLA over the horizon.

Spousal benefits are modeled (see `spousal_excess_annual_benefit`). Not modeled: the earnings test
before FRA; and survivor benefits.
"""
from datetime import date
from decimal import Decimal

from common.datetime_utils import elapsed_months

_EARLY_BREAKPOINT  = 36        # months early at which the reduction rate steps down
_DELAY_CEILING_AGE = 70        # delayed-retirement credits stop accruing at age 70
_MIN_CLAIMING_AGE_MONTHS = 62 * 12   # spousal benefits cannot be claimed before age 62


def realized_annual_benefit(
        pia_monthly : Decimal, birthdate : date, claiming_date : date ) -> Decimal:
    """The annual benefit (today's dollars) for claiming on `claiming_date` -- the PIA scaled by
    the SSA adjustment factor for that claiming month, times twelve."""
    claiming_age_months = elapsed_months( birthdate, claiming_date )
    return pia_monthly * _adjustment_factor( birthdate.year, claiming_age_months ) * Decimal( 12 )


def spousal_excess_annual_benefit(
        pia_high_monthly : Decimal, pia_low_monthly : Decimal,
        low_birthdate : date, low_claiming_date : date ) -> Decimal:
    """The annual spousal top-up (today's dollars) the lower earner receives on top of their own
    benefit: the excess of half the higher earner's PIA over the lower earner's own PIA, reduced for
    claiming before the lower earner's full retirement age. Floors at zero (no top-up once the lower
    earner's own PIA meets half the higher PIA), and is based on the higher earner's PIA -- the
    full-retirement-age amount, not their own claiming-adjusted benefit."""
    excess_monthly = max( Decimal( 0 ), pia_high_monthly / Decimal( 2 ) - pia_low_monthly )
    if excess_monthly <= 0:
        return Decimal( 0 )
    factor = _spousal_factor( low_birthdate.year, elapsed_months( low_birthdate, low_claiming_date ) )
    return excess_monthly * factor * Decimal( 12 )


def full_retirement_age_months( birth_year : int ) -> int:
    """Full retirement age in months per the SSA birth-year schedule: 65 for 1937 and earlier,
    sliding two months a year to 66 for 1943-1954, then to 67 for 1960 and later."""
    if birth_year <= 1937:
        return 65 * 12
    if birth_year <= 1942:
        return 65 * 12 + ( birth_year - 1937 ) * 2
    if birth_year <= 1954:
        return 66 * 12
    if birth_year <= 1959:
        return 66 * 12 + ( birth_year - 1954 ) * 2
    return 67 * 12


def _adjustment_factor( birth_year : int, claiming_age_months : int ) -> Decimal:
    """The fraction of PIA payable for claiming at `claiming_age_months` of age: below 1 before
    FRA, above 1 after, exactly 1 at FRA."""
    fra_months   = full_retirement_age_months( birth_year )
    delta_months = claiming_age_months - fra_months
    if delta_months < 0:
        return Decimal( 1 ) - _early_reduction( -delta_months )
    if delta_months > 0:
        credited = min( delta_months, _DELAY_CEILING_AGE * 12 - fra_months )
        return Decimal( 1 ) + Decimal( credited * 2 ) / Decimal( 300 )   # 2/3 of 1% per month
    return Decimal( 1 )


def _early_reduction( months_early : int ) -> Decimal:
    """The fraction of PIA lost for claiming `months_early` months before FRA: 5/9 of 1% a
    month for the first 36, then 5/12 of 1% a month. The integer month count is multiplied
    before the single division, so whole-percent results stay exact."""
    first  = min( months_early, _EARLY_BREAKPOINT )
    beyond = max( months_early - _EARLY_BREAKPOINT, 0 )
    return Decimal( first * 5 ) / Decimal( 900 ) + Decimal( beyond * 5 ) / Decimal( 1200 )


def _spousal_factor( birth_year : int, claiming_age_months : int ) -> Decimal:
    """The fraction of the spousal excess payable for claiming at `claiming_age_months`: exactly 1 at
    or after full retirement age -- the spousal benefit earns no delayed-retirement credits, so it
    caps at 50% of PIA -- and reduced before it, with the reduction capped at the age-62 maximum
    (claiming a spousal benefit below 62 is not allowed, so it does not reduce further)."""
    fra_months   = full_retirement_age_months( birth_year )
    months_early = fra_months - claiming_age_months
    if months_early <= 0:
        return Decimal( 1 )
    capped = min( months_early, fra_months - _MIN_CLAIMING_AGE_MONTHS )
    return Decimal( 1 ) - _spousal_reduction( capped )


def _spousal_reduction( months_early : int ) -> Decimal:
    """The fraction of the spousal benefit lost for claiming `months_early` months before FRA: 25/36
    of 1% a month for the first 36, then 5/12 of 1% a month. The integer month count is multiplied
    before the single division, so whole-percent results stay exact."""
    first  = min( months_early, _EARLY_BREAKPOINT )
    beyond = max( months_early - _EARLY_BREAKPOINT, 0 )
    return Decimal( first * 25 ) / Decimal( 3600 ) + Decimal( beyond * 5 ) / Decimal( 1200 )
