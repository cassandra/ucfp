"""Level-payment loan amortization -- the standard mortgage/loan math as pure functions over
`Decimal`s, so the forecast engine (per-interval interest/principal booking) and the planning
layer (deriving a loan's current balance from its origination) share one implementation.

`periodic_rate` is the rate per payment period (a monthly mortgage uses the monthly rate), and
`periods` counts those same periods; the caller picks the period and keeps rate and count in step.
"""
from decimal import Decimal
from typing import Optional

ONE = Decimal( '1' )


def level_payment( principal : Decimal, periodic_rate : Decimal, periods : int ) -> Decimal:
    """The level payment that retires `principal` over `periods` at `periodic_rate` per period --
    the standard amortization formula (straight-line when the rate is zero)."""
    if periodic_rate == 0:
        return principal / periods
    discount = ( ONE + periodic_rate ) ** ( -periods )
    return principal * periodic_rate / ( ONE - discount )


def periods_to_repay(
        balance : Decimal, periodic_rate : Decimal, payment : Decimal ) -> Optional[ int ]:
    """The number of level `payment`s needed to retire `balance` at `periodic_rate` per period,
    rounded up to the whole period that clears it -- the counterpart of `level_payment` when the
    payment is known and the term is not. None when the payment cannot retire the balance: a payment
    that does not exceed the first period's interest never brings the balance down. Computed by
    stepping the balance (exact over `Decimal`), which terminates because a qualifying payment
    strictly reduces it each period."""
    if balance <= 0:
        return 0
    if payment <= 0 or ( periodic_rate > 0 and payment <= balance * periodic_rate ):
        return None
    remaining, periods = balance, 0
    while remaining > 0:
        periods += 1
        payoff   = remaining + remaining * periodic_rate
        if payment >= payoff:
            return periods                  # this payment covers the full payoff -- cleared here
        remaining = payoff - payment
    return periods


def present_value(
        payment : Decimal, periodic_rate : Decimal, periods : int ) -> Decimal:
    """The principal that a level `payment` retires over `periods` at `periodic_rate` -- the inverse
    of `level_payment`. Given a known payment and term (e.g. an auto loan's monthly and its term),
    this is the amount financed."""
    if periods <= 0:
        return Decimal( '0' )
    if periodic_rate == 0:
        return payment * periods
    discount = ( ONE + periodic_rate ) ** ( -periods )
    return payment * ( ONE - discount ) / periodic_rate


def rate_for_payment(
        balance : Decimal, payment : Decimal, periods : int ) -> Decimal:
    """The `periodic_rate` at which a level `payment` retires `balance` over `periods` -- `level_payment`
    inverted for the rate (no closed form, so bisected: the payment rises monotonically with the rate).
    Returns 0 when the payment does not exceed the zero-interest payment (`balance / periods`), since no
    positive rate then fits; the search caps at 100%/period, far above any real loan."""
    if periods <= 0 or payment <= balance / periods:
        return Decimal( '0' )
    low, high = Decimal( '0' ), ONE                         # 0 .. 100% per period brackets every real loan
    for _ in range( 60 ):                                   # ~2^-60 precision -- exact to far past a cent
        mid = ( low + high ) / 2
        if level_payment( balance, mid, periods ) < payment:
            low = mid
        else:
            high = mid
    return ( low + high ) / 2


def balance_after(
        principal : Decimal, periodic_rate : Decimal, payment : Decimal, periods : int ) -> Decimal:
    """The balance left after `periods` payments of a fixed `payment` against `principal` growing at
    `periodic_rate` -- unlike `remaining_balance`, the payment is given (not derived from a term), so
    it covers a paydown of any amount (e.g. a card paid at a chosen monthly rate). Clamped at zero
    (a payment that clears the balance leaves nothing, never a negative)."""
    balance = principal
    for _ in range( max( periods, 0 ) ):
        balance += balance * periodic_rate - payment
        if balance <= 0:
            return Decimal( '0' )
    return balance


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
