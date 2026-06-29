"""Social Security retirement-benefit adjustment for claiming date (US).

A standalone `jurisdiction/us` helper the planning layer calls to turn a subject's PIA (primary
insurance amount -- the monthly benefit at full retirement age) into the realized benefit for
a chosen claiming date. The SSA schedule adjusts the benefit by the month: it reduces the
benefit for each month claimed before full retirement age (FRA) and adds delayed-retirement
credits for each month after, up to age 70; FRA slides with birth year (65 for 1937 and
earlier, to 67 for 1960 and later). Benefits are in today's dollars; the engine grows them by
the Social Security COLA over the horizon.

Not modeled: the earnings test before FRA; and family/spousal/survivor benefits.
"""
from datetime import date
from decimal import Decimal

from common.datetime_utils import elapsed_months

_EARLY_BREAKPOINT  = 36   # months early at which the reduction rate steps down
_DELAY_CEILING_AGE = 70   # delayed-retirement credits stop accruing at age 70


def realized_annual_benefit(
        pia_monthly : Decimal, birthdate : date, claiming_date : date ) -> Decimal:
    """The annual benefit (today's dollars) for claiming on `claiming_date` -- the PIA scaled by
    the SSA adjustment factor for that claiming month, times twelve."""
    claiming_age_months = elapsed_months( birthdate, claiming_date )
    return pia_monthly * _adjustment_factor( birthdate.year, claiming_age_months ) * Decimal( 12 )


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
