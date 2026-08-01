"""§7 plan events: one `EventType` handler per kind, over a thin shared base.

An event is a best-effort authoring convenience -- the user adds a money move or a life event, and
it becomes one more input the forecast reads (never a simulation step). Each kind is a small handler
that supplies only what its kind does: the references it needs (a subject, an account), whether it
is offerable in the current plan, how it summarizes, and how it materializes into the engine. The
cross-cutting machinery -- the add menu, availability, the picker form, the events list -- reads
this one uniform surface, so consistency holds without a registry of declarative specs.

A *reference* is the load-bearing concept: an entity the event points at, by `role`, with the valid
candidates drawn from the profile. The picker auto-fills a single candidate and asks only when there
is a real choice -- we never silently default. (Two further modes build on this base: *provision*
creates an implied entity -- a Roth conversion's Roth account -- and *cascade* adjusts other
inputs -- a home sale ending its mortgage.)
"""
from dataclasses import dataclass, replace
from typing import Callable, Optional

from django import forms

from common.recurrence import OneTime
from common.schedule import Schedule

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.parameters import (
    ExpenseItem, IncomeItem, ScheduledExternalDisbursement, ScheduledExternalReceipt,
    ScheduledLoanPayoff, ScheduledRealization, ScheduledTransfer, SubjectRemoval, WindowedAmount )
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind
from ucfp.inputs.plans.schemas import PlanEvent
from ucfp.inputs.widgets import IsoDateInput


# Selection roles -- the canonical keys an event's references, the add form, and its materialization
# all agree on (each is a `PlanEvent.selections` key).
SUBJECT_ROLE   = 'subject'
RECIPIENT_ROLE = 'recipient'
SOURCE_ROLE    = 'source'
TARGET_ROLE    = 'target'
PROPERTY_ROLE  = 'property'
LOAN_ROLE      = 'loan'
CARD_ROLE      = 'card'

# Menu groups, in display order.
_ACCOUNTS_GROUP  = 'Accounts'
_PROPERTY_GROUP  = 'Property'
_MONEY_IN_GROUP  = 'Money in'
_MONEY_OUT_GROUP = 'Money out'
_HOUSEHOLD_GROUP = 'Household'
_GROUP_ORDER     = ( _ACCOUNTS_GROUP, _PROPERTY_GROUP, _MONEY_IN_GROUP, _MONEY_OUT_GROUP,
                     _HOUSEHOLD_GROUP )


@dataclass( frozen = True )
class ReferenceSpec:
    """One reference an event needs to an existing entity the user selects -- its `role` (the
    selection key), a display `label`, and `choices(profile)` yielding the valid `(handle, label)`
    candidates."""
    role    : str
    label   : str
    choices : Callable[ [ object ], list ]


# --- Candidate sources + display helpers ----------------------------------

def _subjects( profile ) -> list:
    return [ ( subject.handle, subject.name ) for subject in profile.subjects ]


def _accounts( profile ) -> list:
    """The money accounts a transfer can move between -- every holding except real estate (a property is
    not a cash account)."""
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.handle is not None and not asset.asset_class.is_real_estate ]


def _properties( profile ) -> list:
    """The real-property holdings a sale can sell -- residence, second home, or rental."""
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.asset_class.is_real_estate ]


def _mortgages( profile, property_handle : str ) -> list:
    """The handles of the debts secured by `property_handle` -- the mortgages a sale pays off. A
    property may carry more than one (e.g. a first and a second), so this is a list, not a flag."""
    return [ debt.handle for debt in profile.debts if debt.secured_asset == property_handle ]


def _names( profile ) -> dict:
    names = { subject.handle: subject.name for subject in profile.subjects }
    names.update( { asset.handle: asset.name for asset in profile.assets } )
    names.update( { debt.handle: debt.name for debt in profile.debts } )
    return names


def _money( amount ) -> str:
    return f'${amount:,.0f}' if amount is not None else ''


# --- The materialization accumulator --------------------------------------

class EventContributions:
    """The engine inputs the Plans' events contribute, bucketed by the `ForecastParameters` list
    each feeds; the materialization merges these into the parameters it assembles."""

    def __init__( self ):
        self.scheduled_events = list()
        self.income_items     = list()
        self.expense_items    = list()
        self.subject_removals = list()
        self.property_sales   = dict()   # property handle -> sale date, for clipping its operating costs


# --- The handler base + the kinds -----------------------------------------

class EventType:
    """One kind of plan event. The common case is a single dated amount feeding one engine input;
    a subclass overrides only the references it needs, its summary, and how it contributes."""

    kind       : EventKind
    group      : str
    has_amount : bool = True

    @property
    def label( self ) -> str:
        return self.kind.label

    def references( self, profile ) -> list:
        return list()

    def offerable( self, profile ) -> bool:
        """Whether this kind can be added to the current plan -- by default, every reference it
        needs has at least one candidate."""
        return all( spec.choices( profile ) for spec in self.references( profile ) )

    def validate( self, selections : dict, profile ) -> Optional[ str ]:
        """A cross-field check on the chosen selections, or None. (The per-reference choice is
        already constrained to valid candidates.)"""
        return None

    def provision( self, event : PlanEvent, profile ):
        """Bring into existence any entity this event implies, returning the (possibly updated)
        profile and event. Runs once, when the event is added; the run then just reads the result.
        The default provisions nothing; a Roth conversion creates the Roth account it lands in."""
        return profile, event

    def cascade_on_add( self, event : PlanEvent, profile, plans ):
        """Adjust other inputs when this event is added. Runs once, at add time (stateless and
        best-effort); the default changes nothing. Returns the (possibly updated) profile and plans.
        (A property sale needs no such cascade -- its rental income and operating expenses are clipped
        to the sale date at materialize, from the event itself.)"""
        return profile, plans

    def cascade_on_remove( self, event : PlanEvent, profile, plans ):
        """Best-effort reverse of `cascade_on_add` when the event is removed."""
        return profile, plans

    def is_materializable( self, event : PlanEvent, profile, plans ) -> bool:
        """Whether this event should contribute to the engine given the current plan -- the guard for
        an event whose target may have gone away or was never realized. The default is always (most
        events stand alone); a loan payoff needs its debt to actually be a materialized loan, else the
        engine has no liability to pay off."""
        return True

    def summary( self, event : PlanEvent, profile ) -> str:
        raise NotImplementedError

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        raise NotImplementedError


class TransferEvent( EventType ):
    kind  = EventKind.TRANSFER
    group = _ACCOUNTS_GROUP

    def references( self, profile ) -> list:
        return [ ReferenceSpec( SOURCE_ROLE, 'From account', _accounts ),
                 ReferenceSpec( TARGET_ROLE, 'To account', _accounts ) ]

    def offerable( self, profile ) -> bool:
        """A meaningful transfer needs two distinct accounts -- the references are correlated, so
        the plain per-reference rule under-constrains."""
        return len( _accounts( profile ) ) >= 2

    def validate( self, selections : dict, profile ) -> Optional[ str ]:
        if selections.get( SOURCE_ROLE ) == selections.get( TARGET_ROLE ):
            return 'Choose two different accounts.'
        return None

    def summary( self, event : PlanEvent, profile ) -> str:
        names = _names( profile )
        return ( f'Transfer {_money( event.amount )} from '
                 f'{names.get( event.selections.get( SOURCE_ROLE ) )} to '
                 f'{names.get( event.selections.get( TARGET_ROLE ) )}' )

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.scheduled_events.append( ScheduledTransfer(
            event_date = event.date, source = event.selections[ SOURCE_ROLE ],
            target = event.selections[ TARGET_ROLE ], amount = event.amount ) )


class SellPropertyEvent( EventType ):
    kind       = EventKind.SELL_PROPERTY
    group      = _PROPERTY_GROUP
    has_amount = False   # the sale price is the projected value, not a user figure

    def references( self, profile ) -> list:
        return [ ReferenceSpec( PROPERTY_ROLE, 'Property', _properties ) ]

    def summary( self, event : PlanEvent, profile ) -> str:
        name   = _names( profile ).get( event.selections.get( PROPERTY_ROLE ) )
        notice = ( ' (mortgage paid off)'
                   if _mortgages( profile, event.selections.get( PROPERTY_ROLE ) ) else '' )
        return f'Sell {name} in {event.date.year}{notice}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        # No amount: a sale realizes the entire holding at its projected value, then pays off any
        # mortgage secured by it from the proceeds (the engine clears the projected balance).
        property_handle = event.selections[ PROPERTY_ROLE ]
        into.property_sales[ property_handle ] = event.date
        into.scheduled_events.append( ScheduledRealization(
            event_date = event.date, holding = property_handle ) )
        for loan_handle in _mortgages( profile, property_handle ):
            into.scheduled_events.append( ScheduledLoanPayoff(
                event_date = event.date, loan = loan_handle ) )
        # A sale needs no income cascade: rental rent is clipped to the sale date at materialize
        # (`_clipped_to_sale`, from this event's `property_sales`), as are the property's operating
        # expenses. Only the mortgage payoff above is contributed here.


class LoanPayoffEvent( EventType ):
    """Pay off an amortizing loan in full on a date -- the engine clears the loan's projected balance
    from cash, so the event carries no amount. Created and edited in the Debt plan step (which holds a
    debt's repayment terms), and shown and removable in the events list, but not offered in the add
    menu: choosing which loan to pay off belongs next to its terms, where the plan knows which debts
    are loans. It contributes only when the debt is actually a materialized loan (its terms are set);
    otherwise there is no liability for the engine to clear."""

    kind       = EventKind.LOAN_PAYOFF
    group      = _MONEY_OUT_GROUP
    has_amount = False

    def offerable( self, profile ) -> bool:
        return False   # created in the Debt plan step, not from the add menu

    def is_materializable( self, event : PlanEvent, profile, plans ) -> bool:
        debt_handle = event.selections.get( LOAN_ROLE )
        return any( repayment.debt_handle == debt_handle for repayment in plans.loan_repayments )

    def summary( self, event : PlanEvent, profile ) -> str:
        name = _names( profile ).get( event.selections.get( LOAN_ROLE ), 'a loan' )
        return f'Pay off {name} in {event.date.year}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.scheduled_events.append( ScheduledLoanPayoff(
            event_date = event.date, loan = event.selections[ LOAN_ROLE ] ) )


class CardPayoffEvent( EventType ):
    """A credit-card lump payoff, in the events list for parity with a loan payoff -- shown, not
    editable, but removable. Unlike a loan, a card is not on the books, so its payoff amount comes
    from the card's plan; this event therefore contributes nothing itself (the payoff is materialized
    from the plan, see `_credit_card_expenses`) and serves only to surface the payoff here and, when
    removed, to clear it from the plan. Created in the card's paydown calculator (the Debt plan
    step), not offered in the add menu."""

    kind       = EventKind.CARD_PAYOFF
    group      = _MONEY_OUT_GROUP
    has_amount = False

    def offerable( self, profile ) -> bool:
        return False   # created in the card paydown calculator, not from the add menu

    def summary( self, event : PlanEvent, profile ) -> str:
        name = _names( profile ).get( event.selections.get( CARD_ROLE ), 'a card' )
        return f'Pay off {name} in {event.date.year}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        pass   # the payoff is materialized from the card's plan, not from this events-list marker

    def cascade_on_remove( self, event : PlanEvent, profile, plans ):
        """Removing the payoff from the events list clears it from the card's plan: a lump (LUMP)
        reverts to carrying the balance, a monthly-plus-lump (COMBO) to the monthly paydown alone."""
        card_handle = event.selections.get( CARD_ROLE )
        kept = list()
        for plan in plans.credit_card_plans:
            if plan.card_handle != card_handle:
                kept.append( plan )
            elif plan.mode is CreditCardPlanMode.COMBO:
                kept.append( replace( plan, mode = CreditCardPlanMode.MONTHLY, target_date = None ) )
            # a LUMP plan is dropped entirely -- the card reverts to being carried
        return profile, replace( plans, credit_card_plans = kept )


class TaxableReceiptEvent( EventType ):
    kind  = EventKind.TAXABLE_RECEIPT
    group = _MONEY_IN_GROUP

    def references( self, profile ) -> list:
        return [ ReferenceSpec( RECIPIENT_ROLE, 'Recipient', _subjects ) ]

    def summary( self, event : PlanEvent, profile ) -> str:
        recipient = _names( profile ).get( event.selections.get( RECIPIENT_ROLE ) )
        return f'Taxable receipt of {_money( event.amount )} to {recipient}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.income_items.append( IncomeItem(
            subject = subjects[ event.selections[ RECIPIENT_ROLE ] ],
            income_tax_class = IncomeTaxClass.ORDINARY,
            amounts = Schedule.constant( WindowedAmount( event.amount ) ),
            cadence = OneTime( event.date ) ) )


class TaxFreeReceiptEvent( EventType ):
    kind  = EventKind.TAX_FREE_RECEIPT
    group = _MONEY_IN_GROUP

    def summary( self, event : PlanEvent, profile ) -> str:
        return f'Tax-free receipt of {_money( event.amount )}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.scheduled_events.append(
            ScheduledExternalReceipt( event_date = event.date, amount = event.amount ) )


class GeneralPaymentEvent( EventType ):
    kind  = EventKind.GENERAL_PAYMENT
    group = _MONEY_OUT_GROUP

    def summary( self, event : PlanEvent, profile ) -> str:
        return f'Payment of {_money( event.amount )}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.scheduled_events.append(
            ScheduledExternalDisbursement( event_date = event.date, amount = event.amount ) )


class _DeductiblePaymentEvent( EventType ):
    """A one-time deductible payment out -- a single expense item carrying its deductible tax class.
    Charitable and medical differ only in that class and their wording."""

    group      = _MONEY_OUT_GROUP
    tax_class  : ExpenseTaxClass
    noun       : str

    def summary( self, event : PlanEvent, profile ) -> str:
        return f'{self.noun} of {_money( event.amount )}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.expense_items.append( ExpenseItem(
            name = f'{self.noun} ({event.date.isoformat()})', expense_tax_class = self.tax_class,
            amounts = Schedule.constant( WindowedAmount( event.amount ) ),
            cadence = OneTime( event.date ) ) )


class CharitablePaymentEvent( _DeductiblePaymentEvent ):
    kind      = EventKind.CHARITABLE_PAYMENT
    tax_class = ExpenseTaxClass.CHARITABLE
    noun      = 'Charitable gift'


class MedicalPaymentEvent( _DeductiblePaymentEvent ):
    kind      = EventKind.MEDICAL_PAYMENT
    tax_class = ExpenseTaxClass.MEDICAL
    noun      = 'Medical expense'


class DeathEvent( EventType ):
    kind       = EventKind.DEATH
    group      = _HOUSEHOLD_GROUP
    has_amount = False

    def references( self, profile ) -> list:
        return [ ReferenceSpec( SUBJECT_ROLE, 'Subject', _subjects ) ]

    def summary( self, event : PlanEvent, profile ) -> str:
        subject = _names( profile ).get( event.selections.get( SUBJECT_ROLE ) )
        return f'Death of {subject} in {event.date.year}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.subject_removals.append( SubjectRemoval(
            event_date = event.date, subject_handle = event.selections[ SUBJECT_ROLE ] ) )


# --- Registry -------------------------------------------------------------

_EVENT_TYPES = (
    TransferEvent(), SellPropertyEvent(), LoanPayoffEvent(),
    CardPayoffEvent(), TaxableReceiptEvent(), TaxFreeReceiptEvent(), GeneralPaymentEvent(),
    CharitablePaymentEvent(), MedicalPaymentEvent(), DeathEvent() )

_BY_KIND = { event_type.kind: event_type for event_type in _EVENT_TYPES }


def handler_for( kind : EventKind ) -> EventType:
    return _BY_KIND[ kind ]


def offerable_menu( profile ) -> list:
    """The offerable kinds, grouped in display order -- (group, [types]) for each non-empty group."""
    offerable = [ event_type for event_type in _EVENT_TYPES if event_type.offerable( profile ) ]
    grouped   = list()
    for group in _GROUP_ORDER:
        members = [ event_type for event_type in offerable if event_type.group == group ]
        if members:
            grouped.append( ( group, members ) )
    return grouped


def event_contributions( profile, plans, subjects : dict ) -> EventContributions:
    """The engine inputs the Plans' events contribute. `subjects` maps a subject handle to the
    materialized engine `Subject` (an income event credits the recipient subject)."""
    into = EventContributions()
    for event in plans.events:
        handler = handler_for( event.kind )
        if handler.is_materializable( event, profile, plans ):
            handler.contribute( event, profile, subjects, into )
    return into


# --- View/template context -------------------------------------------------

def menu_context( profile ) -> list:
    """The add menu for the templates: each group's offerable kinds as `{kind slug, label}`."""
    return [ { 'group': group,
               'types': [ { 'kind': event_type.kind.name.lower(), 'label': event_type.label }
                          for event_type in types ] }
             for group, types in offerable_menu( profile ) ]


def events_context( profile, plans ) -> list:
    """The events list for the templates: each event's row index and human summary."""
    events = plans.events if plans is not None else list()
    return [ { 'index': index, 'summary': handler_for( event.kind ).summary( event, profile ) }
             for index, event in enumerate( events ) ]


# --- Forms ----------------------------------------------------------------

class EventForm( forms.Form ):
    """The add form for one event kind, built from its `EventType`: a date, an amount (when the
    kind carries one), and a picker per reference. A single candidate is shown pre-selected, so the
    user sees and confirms what the event acts on; more than one prepends a placeholder, so the user
    must choose (no silent default). `build_event` returns the `PlanEvent` to append."""

    date = forms.DateField( label = 'Date', widget = IsoDateInput() )

    def __init__( self, data = None, *, event_type = None, profile = None ):
        super().__init__( data )
        self._event_type = event_type
        self._profile    = profile
        if event_type.has_amount:
            self.fields[ 'amount' ] = forms.DecimalField( label = 'Amount', min_value = 0 )
        for spec in event_type.references( profile ):
            self.fields[ self._role_field( spec.role ) ] = forms.ChoiceField(
                label = spec.label, choices = self._choices( spec.choices( profile ) ) )

    @staticmethod
    def _role_field( role : str ) -> str:
        return f'select_{role}'

    @staticmethod
    def _choices( candidates : list ) -> list:
        """The dropdown options for one reference: a lone candidate stands alone (shown selected,
        nothing to pick); several get a leading placeholder that fails the required check, forcing
        a deliberate choice."""
        if len( candidates ) == 1:
            return list( candidates )
        return [ ( '', 'Choose...' ) ] + list( candidates )

    def clean( self ):
        cleaned = super().clean()
        error   = self._event_type.validate( self._selections( cleaned ), self._profile )
        if error:
            raise forms.ValidationError( error )
        return cleaned

    def _selections( self, cleaned : dict ) -> dict:
        return { spec.role: cleaned.get( self._role_field( spec.role ) )
                 for spec in self._event_type.references( self._profile ) }

    def build_event( self ) -> PlanEvent:
        return PlanEvent(
            kind = self._event_type.kind, date = self.cleaned_data[ 'date' ],
            amount = self.cleaned_data.get( 'amount' ),
            selections = self._selections( self.cleaned_data ) )


class EventsForm:
    """§7 L0 -- the plan's events. A no-op section form: events are added and removed through the
    `EventAddView`/`EventDeleteView`, so advancing does nothing but move on. It exposes the current
    events and the offerable kinds for the pane."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile = profile
        self._plans   = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def events( self ) -> list:
        return events_context( self._profile, self._plans )

    @property
    def menu( self ) -> list:
        return menu_context( self._profile )

    def apply( self, profile, plans ):
        return profile, plans
