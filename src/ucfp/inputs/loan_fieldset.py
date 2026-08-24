"""The shared loan-terms fieldset: the loan-solver input fields (rate, term, payment) as reusable
factories every loan-entry surface builds from, plus `solved_loan_terms`, which turns what the user
entered into a consistent `LoanTerms` fact. The Python half of the one loan component -- paired with the
client solver in `inputs.js` and the `_loan_fields.html` partial, all speaking the shared `LOAN_*`
classes so every surface that solicits loan terms looks and behaves the same.

`solved_loan_terms` reuses `common.loan_solver`: the rate is taken as entered, else back-solved from the
payment (plausibility-guarded); the payment is then re-derived from balance + rate + term so the stored
trio is internally consistent. All three are stored even though they are over-determined -- the preferred
authoritative trio is balance + rate + term, with the payment re-derived -- so the user may correct any of
them later without the surface having to remember which three they typed.
"""
from decimal import Decimal
from typing import Optional

from django import forms

from common.forms import MoneyField, PercentField
from common.loan_solver import monthly_payment, resolved_annual_rate
from common.rate import Rate
from common.recurrence import Duration

from ucfp.environment.constants import AppConst
from ucfp.inputs.profile.schemas import LoanTerms


def loan_rate_field( *, initial = None, hint_id : Optional[ str ] = None ) -> PercentField:
    """The interest-rate input (percent). `hint_id` points it (via `aria-describedby`) at the block's
    "doesn't fit" hint, which the solver reveals when a payment/term can't form a real loan."""
    field = PercentField(
        label = 'Rate (%)', required = False, min_value = 0,
        css_class = AppConst.LOAN_RATE_CLASS, initial = initial )
    if hint_id is not None:
        field.widget.attrs[ 'aria-describedby' ] = hint_id
    return field


def loan_term_field( *, initial = None ) -> forms.IntegerField:
    """The remaining-term input, in whole months."""
    return forms.IntegerField(
        label = 'Months left', required = False, min_value = 1,
        widget = forms.NumberInput( attrs = { 'class' : f'form-control {AppConst.LOAN_TERM_CLASS}' } ),
        initial = initial )


def loan_payment_field( *, initial = None ) -> MoneyField:
    """The monthly-payment input -- the number most people know, from which the solver back-solves the
    rate."""
    return MoneyField(
        label = 'Monthly payment', required = False, min_value = 0,
        css_class = AppConst.LOAN_PAYMENT_CLASS, initial = initial )


def solved_loan_terms(
        balance : Optional[ Decimal ], interest_rate : Optional[ Rate ],
        remaining_term : Optional[ Duration ], payment : Optional[ Decimal ] ) -> Optional[ LoanTerms ]:
    """The consistent `LoanTerms` the user's entries imply, or None when no term was entered at all (a
    balance-only loan). The rate is taken as entered, else back-solved from the `payment` over `balance`
    and the term (guarded); the payment is then re-derived from balance + rate + term so the stored trio is
    internally consistent. `balance` is the books fact -- read but not stored on the terms."""
    months = remaining_term.months() if remaining_term is not None else None
    rate   = ( resolved_annual_rate( interest_rate, balance, payment, months )
               if months is not None else interest_rate )
    consistent_payment = payment
    if balance is not None and balance > 0 and rate is not None and months is not None:
        consistent_payment = Decimal( round( monthly_payment( balance, rate, months ) ) )
    if rate is None and remaining_term is None and consistent_payment is None:
        return None
    return LoanTerms( interest_rate = rate, remaining_term = remaining_term,
                      monthly_payment = consistent_payment )
