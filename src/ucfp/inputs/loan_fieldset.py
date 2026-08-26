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
from common.loan_solver import monthly_payment, resolved_annual_rate, resolved_term
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

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
    """The consistent `LoanTerms` the user's entries imply, or None for a loan with no terms at all (a
    balance-only loan). The rate is taken as entered, else back-solved from the `payment` over `balance` and
    the term (guarded). When the term is left blank but balance + rate + payment are given, the term is
    back-solved from the payment instead (the "how long until it's paid off?" direction, guarded). The
    payment is then re-derived from balance + rate + term so the stored trio is internally consistent --
    including where the term was itself derived, matching how the rate back-solve already re-derives the
    payment. `balance` is the books fact -- read but not stored on the terms."""
    months = remaining_term.months() if remaining_term is not None else None
    rate   = ( resolved_annual_rate( interest_rate, balance, payment, months )
               if months is not None else interest_rate )
    if remaining_term is None and rate is not None and payment is not None:
        remaining_term = resolved_term( balance, rate, payment )
        months         = remaining_term.months() if remaining_term is not None else None
    consistent_payment = payment
    if balance is not None and balance > 0 and rate is not None and months is not None:
        consistent_payment = Decimal( round( monthly_payment( balance, rate, months ) ) )
    if rate is None and remaining_term is None and consistent_payment is None:
        return None
    return LoanTerms( interest_rate = rate, remaining_term = remaining_term,
                      monthly_payment = consistent_payment )


def seeded_repayment_terms( debt, repayment ):
    """The rate and remaining term a repayment Plan starts from -- the Plan's own `LoanRepayment` once it
    exists (authoritative, since the user's repayment choice may deliberately differ from the contract),
    else seeded from the Profile `Debt`'s captured contract terms. Returns `(Rate|None, Duration|None)`.
    This is the one place a Plan's rate/term seed from the Profile facts, so the debt-plan and vehicle-plan
    surfaces cannot seed differently."""
    if repayment is not None:
        return repayment.interest_rate, repayment.remaining_term
    if debt is None or debt.terms is None:
        return None, None
    return debt.terms.interest_rate, debt.terms.remaining_term


def loan_terms_initial( terms : Optional[ LoanTerms ] ) -> dict:
    """The shared loan-terms fields' initial values from a stored `LoanTerms` -- rate as a percent, term in
    months, payment as-is; empty when there are none. Merge into a form's `_initial` so an edit reopens on
    the captured terms."""
    if terms is None:
        return dict()
    initial : dict = dict()
    if terms.interest_rate is not None:
        initial[ 'loan_rate' ] = terms.interest_rate.fraction * 100
    if terms.remaining_term is not None:
        initial[ 'loan_term' ] = terms.remaining_term.months()
    if terms.monthly_payment is not None:
        initial[ 'loan_payment' ] = terms.monthly_payment
    return initial


def solved_terms_from_cleaned( cleaned : dict, balance : Optional[ Decimal ] ) -> Optional[ LoanTerms ]:
    """The consistent `LoanTerms` from the shared loan-terms fields in a form's `cleaned_data` and the
    entered `balance` -- None for a balance-only loan (no terms given)."""
    rate    = cleaned.get( 'loan_rate' )
    term    = cleaned.get( 'loan_term' )
    payment = cleaned.get( 'loan_payment' )
    return solved_loan_terms(
        balance,
        Rate.percent( rate ) if rate is not None else None,
        Duration( term, TimeUnit.MONTH ) if term is not None else None,
        payment )


class LoanTermsFieldsMixin:
    """Adds the shared loan-terms fields (`loan_rate`/`loan_term`/`loan_payment`) to a flat, single-loan
    Profile form, and rebuilds the consistent `LoanTerms` from them. The host form keeps its own balance
    field (named to suit -- `mortgage_balance`, `loan_balance`), gives it `AppConst.LOAN_BALANCE_CLASS`,
    seeds the terms by merging `loan_terms_initial( debt.terms )` into its initials, and renders the whole
    block with the `_loan_fields.html` partial (passing `loan_id=form.loan_id`, so the hint id it emits
    matches the one the rate input targets). The Debts row list, whose fields are per-row, builds from the
    factories directly instead of this mixin.

    The fields are injected in `__init__` (after the form builds `self.fields`), not declared as class
    attributes, because Django's form metaclass only collects declared fields from form-class bases -- a
    plain mixin's would be silently dropped.

    `loan_id` is the block's DOM id stem: the hint is `{loan_id}-hint`, which the rate input's
    aria-describedby targets *and* which the host template passes to `_loan_fields.html` -- one source, so
    the two cannot fall out of step. Each host sets a distinct `LOAN_ID` because several loan blocks can
    share a page (the residence and the rental / second-home editors all render on the Real Estate
    section)."""

    LOAN_ID = 'loan'          # the block's id stem; each host overrides it so co-rendered blocks stay unique

    @property
    def loan_id( self ) -> str:
        return self.LOAN_ID

    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        self.fields[ 'loan_rate' ]    = loan_rate_field( hint_id = f'{self.loan_id}-hint' )
        self.fields[ 'loan_term' ]    = loan_term_field()
        self.fields[ 'loan_payment' ] = loan_payment_field()

    def loan_terms( self, balance : Optional[ Decimal ] ) -> Optional[ LoanTerms ]:
        """The consistent `LoanTerms` the form's entered fields and `balance` imply."""
        return solved_terms_from_cleaned( self.cleaned_data, balance )
