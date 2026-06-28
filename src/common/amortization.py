"""Level-payment loan amortization -- the standard mortgage/loan math as pure functions over
`Decimal`s, so the forecast engine (per-interval interest/principal booking) and the planning
layer (deriving a loan's current balance from its origination) share one implementation.

`periodic_rate` is the rate per payment period (a monthly mortgage uses the monthly rate), and
`periods` counts those same periods; the caller picks the period and keeps rate and count in step.
"""
from decimal import Decimal

ONE = Decimal( '1' )


def level_payment( principal : Decimal, periodic_rate : Decimal, periods : int ) -> Decimal:
    """The level payment that retires `principal` over `periods` at `periodic_rate` per period --
    the standard amortization formula (straight-line when the rate is zero)."""
    if periodic_rate == 0:
        return principal / periods
    discount = ( ONE + periodic_rate ) ** ( -periods )
    return principal * periodic_rate / ( ONE - discount )


def remaining_balance(
        principal : Decimal, periodic_rate : Decimal, periods : int, elapsed : int ) -> Decimal:
    """The balance still owed after `elapsed` level payments on `principal` amortized over
    `periods` at `periodic_rate`. Clamped to the loan's life: the whole principal stands before the
    first payment, and the balance is zero at or beyond the final payment."""
    if elapsed <= 0:
        return principal
    if elapsed >= periods:
        return Decimal( '0' )
    if periodic_rate == 0:
        return principal * Decimal( periods - elapsed ) / Decimal( periods )
    payment = level_payment( principal, periodic_rate, periods )
    growth  = ( ONE + periodic_rate ) ** elapsed
    return principal * growth - payment * ( growth - ONE ) / periodic_rate
