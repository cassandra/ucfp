"""§ Debt plan: how each amortizing debt is repaid -- the Plans side of the Debts facts.

A Profile `Debt` records only what is owed (its current balance). This step captures how an amortizing
debt (mortgage, student, personal, other) is paid down: its interest rate and remaining term -- the
`LoanRepayment` that, composed with the balance, materializes the engine loan -- plus any recurring
extra principal (`LoanPrepayment`). The credit card -- the one non-loan debt kind -- is not a loan
and is handled separately. Reads the declared debts; writes only Plans.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField, PercentField
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.environment.constants import AppConst
from ucfp.inputs.events import LOAN_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import LoanPrepayment, LoanRepayment, PlanEvent
from ucfp.inputs.widgets import IsoDateInput


class DebtPlanForm( forms.Form ):
    """The repayment terms for each amortizing debt, as one auto-saving pane: per debt an interest
    rate, a remaining term in months, optional extra principal per month, and an optional full-payoff
    date. Non-blocking: a debt's loan materializes only once both its rate and term are set (an
    incomplete pair writes nothing), and the extra principal and payoff ride only on complete terms.
    `apply` rebuilds the repayment and prepayment plans for these debts, plus their payoff events
    (`LOAN_PAYOFF`, which the events list also shows), leaving anything belonging to other debts
    intact."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._debts = ( [ debt for debt in profile.debts if debt.kind.is_amortizing ]
                        if profile is not None else [] )
        repayments = { r.debt_handle : r for r in ( plans.loan_repayments if plans else [] ) }
        extra      = { p.loan_handle : p.annual_amount for p in ( plans.prepayments if plans else [] ) }
        payoffs    = self._payoff_dates( plans )
        for debt in self._debts:
            self._build_fields( debt, repayments.get( debt.handle ), extra.get( debt.handle ),
                                payoffs.get( debt.handle ) )

    @staticmethod
    def _payoff_dates( plans ) -> dict:
        """The date of each debt's full-payoff event, by debt handle -- the payoff being a
        `LOAN_PAYOFF` plan event keyed to the loan, shared with the events list."""
        return { event.selections.get( LOAN_ROLE ) : event.date
                 for event in ( plans.events if plans else [] )
                 if event.kind is EventKind.LOAN_PAYOFF }

    def _build_fields( self, debt, repayment, extra_annual, payoff_date ):
        self.fields[ self._rate_field( debt.handle ) ] = PercentField(
            label = 'Interest rate (%)', required = False, min_value = 0,
            css_class = AppConst.LOAN_RATE_CLASS,
            initial = repayment.interest_rate.fraction * 100 if repayment is not None else None )
        self.fields[ self._term_field( debt.handle ) ] = forms.IntegerField(
            label = 'Months remaining', required = False, min_value = 1,
            widget = forms.NumberInput( attrs = { 'class' : AppConst.LOAN_TERM_CLASS } ),
            initial = repayment.remaining_term.months() if repayment is not None else None )
        self.fields[ self._extra_field( debt.handle ) ] = MoneyField(
            label = 'Extra principal per month (optional)', required = False, min_value = 0,
            css_class = AppConst.LOAN_EXTRA_CLASS,
            initial = extra_annual / 12 if extra_annual else None )
        self.fields[ self._payoff_field( debt.handle ) ] = forms.DateField(
            label = 'Pay off in full on (optional)', required = False,
            widget = IsoDateInput(), initial = payoff_date )

    @staticmethod
    def _rate_field( handle : str ) -> str:
        return f'rate_{handle}'

    @staticmethod
    def _term_field( handle : str ) -> str:
        return f'term_{handle}'

    @staticmethod
    def _extra_field( handle : str ) -> str:
        return f'extra_{handle}'

    @staticmethod
    def _payoff_field( handle : str ) -> str:
        return f'payoff_{handle}'

    @property
    def has_debts( self ) -> bool:
        return bool( self._debts )

    @property
    def rows( self ) -> list:
        return [ { 'name'    : debt.name,
                   'kind'    : debt.kind.label,
                   'balance' : debt.balance,
                   'rate'    : self[ self._rate_field( debt.handle ) ],
                   'term'    : self[ self._term_field( debt.handle ) ],
                   'extra'   : self[ self._extra_field( debt.handle ) ],
                   'payoff'  : self[ self._payoff_field( debt.handle ) ] }
                 for debt in self._debts ]

    def apply( self, profile, plans ):
        handles     = { debt.handle for debt in self._debts }
        repayments  = [ r for r in plans.loan_repayments if r.debt_handle not in handles ]
        prepays     = [ p for p in plans.prepayments if p.loan_handle not in handles ]
        # Preserve every event except this form's debts' payoffs, which we re-derive below.
        kept_events = [ event for event in plans.events
                        if not ( event.kind is EventKind.LOAN_PAYOFF
                                 and event.selections.get( LOAN_ROLE ) in handles ) ]
        payoffs = []
        for debt in self._debts:
            repayment, prepayment = self._plan_for( debt )
            if repayment is None:
                continue                    # no terms -> no loan, so no repayment, prepay, or payoff
            repayments.append( repayment )
            if prepayment is not None:
                prepays.append( prepayment )
            payoff = self._payoff_for( debt )
            if payoff is not None:
                payoffs.append( payoff )
        return profile, replace(
            plans, loan_repayments = repayments, prepayments = prepays,
            events = kept_events + payoffs )

    def _plan_for( self, debt ):
        # Non-blocking: terms are a pair -- a rate without a term (or the reverse) is mid-entry, so
        # no loan is written; extra principal rides only on complete terms.
        cleaned = self.cleaned_data
        rate    = cleaned.get( self._rate_field( debt.handle ) )
        term    = cleaned.get( self._term_field( debt.handle ) )
        extra   = cleaned.get( self._extra_field( debt.handle ) )
        if rate is None or term is None:
            return None, None
        repayment  = LoanRepayment(
            debt_handle = debt.handle, interest_rate = Rate.percent( rate ),
            remaining_term = Duration( term, TimeUnit.MONTH ) )
        prepayment = ( LoanPrepayment( loan_handle = debt.handle, annual_amount = extra * 12 )
                       if extra else None )
        return repayment, prepayment

    def _payoff_for( self, debt ):
        # A full-payoff event for the loan, when a date is set (only reached for a debt with complete
        # terms, so the engine has a liability to clear). Keyed to the debt by `LOAN_ROLE`, so the
        # events list summarizes and can remove the same event.
        payoff_date = self.cleaned_data.get( self._payoff_field( debt.handle ) )
        if payoff_date is None:
            return None
        return PlanEvent(
            kind = EventKind.LOAN_PAYOFF, date = payoff_date,
            selections = { LOAN_ROLE : debt.handle } )
