"""The loan solver: derive a level-payment loan's missing term from the ones the user gave, guarding the
back-solve for plausibility, so every loan-entry surface shares one implementation over the four loan
quantities -- balance, rate, term (months), and monthly payment. Built on `common.amortization`, and
mirrored client-side by the loan calculator in `inputs.js` (the two cannot drift because the plausibility
ceiling has one source, re-exported to the client through `AppConst`).

Only the payment->rate back-solve is guarded: a monthly that cannot retire the balance in the term, or
that implies a rate above `MAX_PLAUSIBLE_APR`, does not form a real loan, so no rate is fabricated from
it. A directly-entered rate is trusted as given.
"""
from decimal import Decimal
from typing import Optional

from common.amortization import level_payment, rate_for_payment
from common.rate import Rate


# The APR ceiling above which a payment-derived rate reads as "doesn't fit" -- a monthly implying, say,
# 60%/yr is not a real loan. One source: this value is re-exported through `AppConst` to the client
# calculator (`window.AppConst`), so the client mirror and the server back-solve share the same ceiling.
MAX_PLAUSIBLE_APR_PERCENT = 30
MAX_PLAUSIBLE_APR         = Rate.percent( MAX_PLAUSIBLE_APR_PERCENT )


def monthly_payment( balance : Decimal, annual_rate : Rate, months : int ) -> Decimal:
    """The level monthly payment that retires `balance` over `months` at `annual_rate` -- the rate view of
    a loan turned into its payment view (the annual rate taken per month)."""
    return level_payment( balance, annual_rate.fraction / 12, months )


def plausible_rate_from_payment(
        balance : Decimal, payment : Decimal, months : int ) -> Optional[ Rate ]:
    """The annual `Rate` a `payment`/month implies over `balance` and `months`, or None when it does not
    form a plausible loan -- the payment cannot retire the balance in the term (total payments below it),
    or the implied rate exceeds `MAX_PLAUSIBLE_APR`. So an inconsistent payment/term never yields a bogus
    rate."""
    if payment * months < balance:                   # cannot retire the balance in the term at any rate
        return None
    rate = Rate( rate_for_payment( balance, payment, months ) * 12 )
    return rate if rate.fraction <= MAX_PLAUSIBLE_APR.fraction else None


def resolved_annual_rate(
        entered_rate : Optional[ Rate ], balance : Optional[ Decimal ],
        payment : Optional[ Decimal ], months : int ) -> Optional[ Rate ]:
    """A loan's annual rate from whichever terms the user supplied: a directly-entered rate stands as
    given; otherwise it is back-solved from the monthly `payment` over `balance` and `months` (the no-JS
    fallback, plausibility-guarded). None when neither determines a rate (no rate entered and no usable
    payment/balance)."""
    if entered_rate is not None:
        return entered_rate
    if payment is None or balance is None or balance <= 0:
        return None
    return plausible_rate_from_payment( balance, payment, months )
