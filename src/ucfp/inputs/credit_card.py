"""§ Debt plan: how each credit card will be paid down.

A credit-card `Debt` is never a loan; this form solicits the user's paydown strategy per card -- pay a
set amount each month, clear it by a date, pay it off in one lump, or just keep carrying it -- and
stores it as a `CreditCardPlan` (intent). Materialization resolves that intent into expenses at an
assumed APR, so the stored plan never goes stale against the balance. The live "how long / how much"
figures are advisory, computed client-side (`inputs.js`) from the same shared APR; the authoritative
resolution is server-side.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField
from common.widgets import MoneyInput

from ucfp.environment.constants import AppConst
from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.events import CARD_ROLE
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind
from ucfp.inputs.plans.schemas import CreditCardPlan, PlanEvent
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.widgets import IsoDateInput


# The modes whose plan includes a one-time payoff, surfaced in the events list as a CARD_PAYOFF.
_PAYOFF_MODES = ( CreditCardPlanMode.LUMP, CreditCardPlanMode.COMBO )

# The assumed monthly interest rate the calculator and materialization share -- used here only to warn
# when a monthly payment would not cover it (materialization is authoritative).
_CARD_MONTHLY_RATE = BUILTIN_ASSUMPTIONS.credit_card_apr.fraction / Decimal( '12' )


# The "just keep carrying it" choice -- the absence of a plan, so it maps to no `CreditCardPlan`
# rather than a mode. It is the default when a card has no plan yet.
_CARRY = 'carry'


class CreditCardPlanForm( forms.Form ):
    """A paydown strategy per credit-card debt, as one auto-saving pane. Each card has a mode switch
    (carry / monthly / by-date / lump) and the inputs its active mode needs -- a monthly amount, or a
    target/payoff date. Non-blocking: a card materializes a plan only once its mode's input is set;
    carrying it (or a half-entered mode) stores nothing. `apply` rebuilds the card plans for these
    cards, leaving any belonging to other cards intact."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._cards = ( [ debt for debt in profile.debts if debt.kind is DebtKind.CREDIT_CARD ]
                        if profile is not None else [] )
        self._existing = { plan.card_handle : plan
                           for plan in ( plans.credit_card_plans if plans else [] ) }
        for card in self._cards:
            self._build_fields( card, self._existing.get( card.handle ) )

    def _build_fields( self, card, plan ):
        self.fields[ self._mode_field( card.handle ) ] = forms.ChoiceField(
            required = False, choices = self._mode_choices(),
            initial = plan.mode.name if plan is not None else _CARRY,
            widget = forms.RadioSelect( attrs = { 'class' : AppConst.SWITCH_CONTROL_CLASS } ) )
        self.fields[ self._monthly_field( card.handle ) ] = MoneyField(
            label = 'Monthly payment', required = False, min_value = 0,
            initial = plan.monthly_payment if plan is not None else None,
            widget = MoneyInput( attrs = { 'class' : AppConst.CREDIT_CARD_MONTHLY_CLASS } ) )
        self.fields[ self._date_field( card.handle ) ] = forms.DateField(
            label = 'Date', required = False,
            initial = plan.target_date if plan is not None else None,
            widget = IsoDateInput( attrs = {
                'class' : f'{AppConst.DATE_FIELD_CLASS} {AppConst.CREDIT_CARD_DATE_CLASS}' } ) )

    @staticmethod
    def _mode_choices() -> list:
        return ( [ ( _CARRY, 'Just keep carrying it' ) ]
                 + [ ( mode.name, mode.label ) for mode in CreditCardPlanMode ] )

    @staticmethod
    def _mode_field( handle : str ) -> str:
        return f'mode_{handle}'

    @staticmethod
    def _monthly_field( handle : str ) -> str:
        return f'monthly_{handle}'

    @staticmethod
    def _date_field( handle : str ) -> str:
        return f'date_{handle}'

    @property
    def has_cards( self ) -> bool:
        return bool( self._cards )

    @property
    def apr_percent( self ) -> int:
        """The assumed card APR as a percent -- rendered onto each card widget for the client readout
        and shown in the note, from the same `BUILTIN_ASSUMPTIONS` value materialization resolves at,
        so the estimate and the forecast agree."""
        return int( BUILTIN_ASSUMPTIONS.credit_card_apr.fraction * 100 )

    @property
    def rows( self ) -> list:
        return [ { 'name'    : card.name,
                   'balance' : card.balance,
                   'mode'    : self[ self._mode_field( card.handle ) ],
                   'monthly' : self[ self._monthly_field( card.handle ) ],
                   'date'    : self[ self._date_field( card.handle ) ],
                   'hint'    : self._payment_hint( card ) }
                 for card in self._cards ]

    def _payment_hint( self, card ) -> str:
        """A non-blocking warning when a saved monthly payment does not cover the card's interest, so
        it never clears the balance. The materialization models the payment as entered (it does not
        silently substitute the interest), so this tells the user the plan will not pay the card down.
        Derived from the saved plan; the live equivalent is the client-side calculator readout."""
        plan = self._existing.get( card.handle )
        if ( plan is None or plan.mode is not CreditCardPlanMode.MONTHLY
                or plan.monthly_payment is None ):
            return ''
        if plan.monthly_payment <= card.balance * _CARD_MONTHLY_RATE:
            return "This payment doesn't cover the interest, so the balance won't clear."
        return ''

    def apply( self, profile, plans ):
        handles   = { card.handle for card in self._cards }
        new_plans = self._plans()
        kept_plans = [ plan for plan in plans.credit_card_plans if plan.card_handle not in handles ]
        # Re-derive the card-payoff events for these cards (kept for the events list); leave every
        # other event, and other cards' payoffs, intact.
        kept_events = [ event for event in plans.events
                        if not ( event.kind is EventKind.CARD_PAYOFF
                                 and event.selections.get( CARD_ROLE ) in handles ) ]
        payoffs = [ PlanEvent( kind = EventKind.CARD_PAYOFF, date = plan.target_date,
                               selections = { CARD_ROLE : plan.card_handle } )
                    for plan in new_plans if plan.mode in _PAYOFF_MODES ]
        return profile, replace(
            plans, credit_card_plans = kept_plans + new_plans, events = kept_events + payoffs )

    def _plans( self ) -> list:
        plans = []
        for card in self._cards:
            plan = self._plan_for( card )
            if plan is not None:
                plans.append( plan )
        return plans

    def _plan_for( self, card ):
        # Non-blocking: a card materializes a plan only once its mode's input(s) are set; carrying it
        # (or a half-entered mode) stores nothing -- and carrying is materialized straight from the
        # balance, so it needs no stored plan.
        cleaned = self.cleaned_data
        mode    = cleaned.get( self._mode_field( card.handle ) )
        if not mode or mode == _CARRY:
            return None
        plan_mode = CreditCardPlanMode[ mode ]
        payment   = cleaned.get( self._monthly_field( card.handle ) )
        target    = cleaned.get( self._date_field( card.handle ) )
        if plan_mode is CreditCardPlanMode.MONTHLY:
            return ( CreditCardPlan( card_handle = card.handle, mode = plan_mode,
                                     monthly_payment = payment ) if payment is not None else None )
        if plan_mode is CreditCardPlanMode.COMBO:
            return ( CreditCardPlan( card_handle = card.handle, mode = plan_mode,
                                     monthly_payment = payment, target_date = target )
                     if payment is not None and target is not None else None )
        # BY_DATE or LUMP: a single date.
        return ( CreditCardPlan( card_handle = card.handle, mode = plan_mode, target_date = target )
                 if target is not None else None )
