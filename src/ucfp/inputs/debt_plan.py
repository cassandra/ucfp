"""§ Debt plan: how each amortizing debt is repaid -- the Plans side of the Debts facts.

A Profile `Debt` records what is owed (its current balance) and, as facts, its contract terms. This step
captures how an amortizing debt (mortgage, student, personal, other) is *planned* to be paid down: its
interest rate and remaining term -- the `LoanRepayment` that, composed with the balance, materializes the
engine loan -- plus any recurring extra principal (`LoanPrepayment`). Each debt's rate/term seed from the
Profile contract facts until a repayment is saved, after which the Plan owns its copy (the repayment may
deliberately differ from the contract). Auto loans are authored in the Vehicle plan and shown here
read-only with a pointer; the credit card is not a loan and is handled separately. Writes only Plans.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField, PercentField
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.environment.constants import AppConst
from ucfp.inputs.events import LOAN_ROLE
from ucfp.inputs.compatibility import preserved_snapshot
from ucfp.inputs.loan_fieldset import seeded_repayment_terms
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import LoanPrepayment, LoanRepayment, PlanEvent
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.widgets import MonthField


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
        amortizing = ( [ debt for debt in profile.debts if debt.kind.is_amortizing ]
                       if profile is not None else [] )
        # Non-auto amortizing debts are editable here; auto loans are authored in the Vehicle plan and
        # shown read-only with a pointer. `apply` rebuilds only the editable debts' repayments, so an auto
        # loan's repayment (and anything else) is left intact.
        self._editable   = [ debt for debt in amortizing if debt.kind is not DebtKind.AUTO ]
        self._auto       = [ debt for debt in amortizing if debt.kind is DebtKind.AUTO ]
        self._repayments = { r.debt_handle : r for r in ( plans.loan_repayments if plans else [] ) }
        extra   = { p.loan_handle : p.annual_amount for p in ( plans.prepayments if plans else [] ) }
        payoffs = self._payoff_dates( plans )
        for debt in self._editable:
            self._build_fields( debt, self._repayments.get( debt.handle ), extra.get( debt.handle ),
                                payoffs.get( debt.handle ) )

    @staticmethod
    def _payoff_dates( plans ) -> dict:
        """The date of each debt's full-payoff event, by debt handle -- the payoff being a
        `LOAN_PAYOFF` plan event keyed to the loan, shared with the events list."""
        return { event.selections.get( LOAN_ROLE ) : event.date
                 for event in ( plans.events if plans else [] )
                 if event.kind is EventKind.LOAN_PAYOFF }

    def _build_fields( self, debt, repayment, extra_annual, payoff_date ):
        # Rate and term seed from the repayment once it exists, else from the Profile contract facts.
        rate, term = seeded_repayment_terms( debt, repayment )
        self.fields[ self._rate_field( debt.handle ) ] = PercentField(
            label = 'Rate (%)', required = False, min_value = 0,
            css_class = AppConst.LOAN_RATE_CLASS,
            initial = rate.fraction * 100 if rate is not None else None )
        self.fields[ self._term_field( debt.handle ) ] = forms.IntegerField(
            label = 'Months left', required = False, min_value = 1,
            widget = forms.NumberInput( attrs = { 'class' : f'form-control {AppConst.LOAN_TERM_CLASS}' } ),
            initial = term.months() if term is not None else None )
        self.fields[ self._extra_field( debt.handle ) ] = MoneyField(
            label = 'Extra/month', required = False, min_value = 0,
            css_class = AppConst.LOAN_EXTRA_CLASS,
            initial = extra_annual / 12 if extra_annual else None )
        self.fields[ self._payoff_field( debt.handle ) ] = MonthField(
            label = 'Pay off by', required = False, initial = payoff_date )

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
        return bool( self._editable or self._auto )

    @property
    def rows( self ) -> list:
        return [ { 'name'            : debt.name,
                   'kind'            : debt.kind.label,
                   'balance'         : debt.balance,
                   'balance_display' : f'${debt.balance:,.0f}' if debt.balance is not None else '',
                   'rate'            : self[ self._rate_field( debt.handle ) ],
                   'term'            : self[ self._term_field( debt.handle ) ],
                   'extra'           : self[ self._extra_field( debt.handle ) ],
                   'payoff'          : self[ self._payoff_field( debt.handle ) ] }
                 for debt in self._editable ]

    @property
    def auto_rows( self ) -> list:
        """The household's auto loans, read-only here -- their repayment is authored in the Vehicle plan.
        Each shows its balance and a summary of its current plan terms (or a prompt to set them)."""
        return [ { 'name'            : debt.name,
                   'balance_display' : f'${debt.balance:,.0f}' if debt.balance is not None else '',
                   'terms'           : self._auto_terms_summary( self._repayments.get( debt.handle ) ) }
                 for debt in self._auto ]

    @staticmethod
    def _auto_terms_summary( repayment ) -> str:
        if repayment is None:
            return 'Terms set in the Vehicle plan'
        percent   = repayment.interest_rate.fraction * 100
        rate_text = f'{percent:.2f}'.rstrip( '0' ).rstrip( '.' )   # 5.00 -> 5, 5.50 -> 5.5
        return f'{rate_text}%, {repayment.remaining_term.months()} mo left'

    def apply( self, profile, plans ):
        handles     = { debt.handle for debt in self._editable }
        repayments  = [ r for r in plans.loan_repayments if r.debt_handle not in handles ]
        prepays     = [ p for p in plans.prepayments if p.loan_handle not in handles ]
        # Snapshots for this form's debts are dropped unless a repayment is (re)written below -- a debt with
        # no repayment has no snapshot. Others are preserved untouched.
        snapshots   = [ s for s in plans.loan_terms_snapshots if s.debt_handle not in handles ]
        # Preserve every event except this form's debts' payoffs, which we re-derive below.
        kept_events = [ event for event in plans.events
                        if not ( event.kind is EventKind.LOAN_PAYOFF
                                 and event.selections.get( LOAN_ROLE ) in handles ) ]
        payoffs = []
        for debt in self._editable:
            repayment, prepayment = self._plan_for( debt )
            if repayment is None:
                continue                    # no terms -> no loan, so no repayment, prepay, payoff, snapshot
            repayments.append( repayment )
            snapshots.append( preserved_snapshot( plans, debt.handle, debt.terms ) )
            if prepayment is not None:
                prepays.append( prepayment )
            payoff = self._payoff_for( debt )
            if payoff is not None:
                payoffs.append( payoff )
        return profile, replace(
            plans, loan_repayments = repayments, prepayments = prepays,
            loan_terms_snapshots = snapshots, events = kept_events + payoffs )

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
