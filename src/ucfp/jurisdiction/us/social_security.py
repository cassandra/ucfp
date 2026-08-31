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

`estimated_pia_monthly` runs the other direction -- it *estimates* a PIA from a subject's covered
wages (the SSA benefit formula) for the FRA-benefit estimator, where the claiming schedule above then
takes over. Its bend points are wage-indexed year to year and so live with the other annual figures in
`parameters.py`; the 90 / 32 / 15 percent marginal rates are structural to the formula and live here.
"""
from datetime import date
from decimal import Decimal

from common.datetime_utils import elapsed_months

from .parameters import SocialSecurityBenefitFormula, federal_2026

_EARLY_BREAKPOINT  = 36        # months early at which the reduction rate steps down
_DELAY_CEILING_AGE = 70        # delayed-retirement credits stop accruing at age 70
_MIN_CLAIMING_AGE_MONTHS = 62 * 12   # spousal benefits cannot be claimed before age 62

# The structural marginal replacement rates of the PIA formula: 90% of AIME up to the first bend point,
# 32% between the bends, 15% above the second. Fixed in the benefit formula (not projected year to year),
# so they live here with the math; the bend points they apply to are the annual figures in `parameters.py`.
_PIA_RATE_FIRST  = Decimal( '0.90' )
_PIA_RATE_SECOND = Decimal( '0.32' )
_PIA_RATE_THIRD  = Decimal( '0.15' )


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


def estimated_pia_monthly(
        annual_covered_wage : Decimal, benefit_formula : SocialSecurityBenefitFormula,
        wage_base : Decimal ) -> Decimal:
    """Estimate the monthly PIA (the benefit at full retirement age) from a subject's annual covered
    wage, via the SSA benefit formula. The wage is capped at the Social Security `wage_base` (earnings
    above it are not covered) and spread over twelve months to stand in for AIME -- a typical-career-year
    proxy in today's dollars, which holds because wages and benefits both track wage/price growth. The
    formula then applies 90% of AIME up to the first bend point, 32% between the bends, and 15% above the
    second. Pure: the bend points and wage base are passed in (the annual figures from `parameters.py`),
    not read here."""
    aime   = min( annual_covered_wage, wage_base ) / Decimal( 12 )
    first  = min( aime, benefit_formula.first_bend )
    second = max( Decimal( 0 ), min( aime, benefit_formula.second_bend ) - benefit_formula.first_bend )
    third  = max( Decimal( 0 ), aime - benefit_formula.second_bend )
    return _PIA_RATE_FIRST * first + _PIA_RATE_SECOND * second + _PIA_RATE_THIRD * third


def estimated_pia_monthly_current( annual_covered_wage : Decimal ) -> Decimal:
    """`estimated_pia_monthly` using the current base-year statutory figures -- the entry point the
    jurisdiction facade calls, so callers estimate in today's dollars without handling the parameters."""
    params = federal_2026()
    return estimated_pia_monthly(
        annual_covered_wage, params.ss_benefit_formula, params.fica_rules.ss_wage_base )


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
