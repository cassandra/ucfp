"""§7 plan events: one `EventType` handler per kind, over a thin shared base.

An event is a best-effort authoring convenience -- the user adds a money move or a life event, and
it becomes one more input the forecast reads (never a simulation step). Each kind is a small handler
that supplies only what its kind does: the references it needs (a subject, an account), whether it
is offerable in the current plan, how it summarizes, and how it materializes into the engine. The
cross-cutting machinery -- the add menu, availability, the picker form, the events list -- reads
this one uniform surface, so consistency holds without a registry of declarative specs.

A *reference* is the load-bearing concept: an entity the event points at, by `role`, with the valid
candidates drawn from the profile. The picker auto-fills a single candidate and asks only when there
is a real choice -- we never silently default. (Two later modes attach here additively: *provision*,
to create an implied entity -- a Roth conversion's Roth account -- and *cascade*, to adjust other
inputs -- a home sale ending its mortgage. Neither exists yet.)
"""
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable, Optional

from django import forms

from common.recurrence import OneTime
from common.schedule import Schedule

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.parameters import (
    ExpenseItem, IncomeItem, ScheduledExternalDisbursement, ScheduledExternalReceipt,
    ScheduledRealization, ScheduledTransfer, SubjectRemoval, WindowedAmount )
from ucfp.profile.schemas import AssetProfile
from ucfp.scenario.enums import EventKind
from ucfp.scenario.schemas import PlanEvent


# Selection roles -- the canonical keys an event's references, the add form, and its materialization
# all agree on (each is a `PlanEvent.selections` key).
SUBJECT_ROLE   = 'subject'
RECIPIENT_ROLE = 'recipient'
SOURCE_ROLE    = 'source'
TARGET_ROLE    = 'target'
PROPERTY_ROLE  = 'property'

# Menu groups, in display order.
_ACCOUNTS_GROUP  = 'Accounts'
_PROPERTY_GROUP  = 'Property'
_MONEY_IN_GROUP  = 'Money in'
_MONEY_OUT_GROUP = 'Money out'
_HOUSEHOLD_GROUP = 'Household'
_GROUP_ORDER     = ( _ACCOUNTS_GROUP, _PROPERTY_GROUP, _MONEY_IN_GROUP, _MONEY_OUT_GROUP,
                     _HOUSEHOLD_GROUP )

# Real-estate classes: excluded from money transfers, and the candidates a sale sells.
_REAL_ESTATE = frozenset(
    ( AssetClass.REAL_ESTATE_RESIDENCE, AssetClass.REAL_ESTATE_RENTAL ) )


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
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.handle is not None and asset.asset_class not in _REAL_ESTATE ]


def _properties( profile ) -> list:
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.asset_class in _REAL_ESTATE ]


def _has_mortgage( profile, property_handle : str ) -> bool:
    return any( loan.property_handle == property_handle for loan in profile.loans )


def _end_schedule( schedule : list, end_date ) -> list:
    """A copy of `schedule` ended at `end_date`: segments starting after it are dropped, and any open
    or later end is capped at it -- so the flow is zero past the sale."""
    ended = list()
    for windowed in schedule:
        if windowed.window.start is not None and windowed.window.start > end_date:
            continue
        window = windowed.window
        if window.end is None or window.end > end_date:
            window = replace( window, end = end_date )
        ended.append( replace( windowed, window = window ) )
    return ended


def _reopen_schedule( schedule : list, end_date ) -> list:
    """Best-effort reverse of `_end_schedule`: re-open segments a sale had capped exactly at
    `end_date`."""
    return [ replace( w, window = replace( w.window, end = None ) ) if w.window.end == end_date else w
             for w in schedule ]


def _end_property_flows( profile, scenario, property_handle : str, sale_date ):
    """End the sold property's rental income and operating expenses at `sale_date`. Its mortgage is
    left running -- a scheduled loan payoff is not modeled yet (see the sale's summary notice)."""
    incomes  = [ replace( income, end = sale_date )
                 if income.property_handle == property_handle else income
                 for income in profile.rental_incomes ]
    expenses = [ replace( expense, schedule = _end_schedule( expense.schedule, sale_date ) )
                 if expense.property_handle == property_handle else expense
                 for expense in scenario.expenses ]
    return replace( profile, rental_incomes = incomes ), replace( scenario, expenses = expenses )


def _reopen_property_flows( profile, scenario, property_handle : str, sale_date ):
    incomes  = [ replace( income, end = None )
                 if income.property_handle == property_handle and income.end == sale_date
                 else income
                 for income in profile.rental_incomes ]
    expenses = [ replace( expense, schedule = _reopen_schedule( expense.schedule, sale_date ) )
                 if expense.property_handle == property_handle else expense
                 for expense in scenario.expenses ]
    return replace( profile, rental_incomes = incomes ), replace( scenario, expenses = expenses )


def _pretax_accounts( profile ) -> list:
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.asset_class is AssetClass.PRETAX_RETIREMENT ]


# The handle minted for a Roth account a conversion provisions for an owner who has none.
_ROTH_HANDLE_PREFIX = 'roth-'


def _owner_of( profile, handle : str ) -> Optional[ str ]:
    asset = next( ( asset for asset in profile.assets if asset.handle == handle ), None )
    return asset.owner_handle if asset is not None else None


def _subject_name( profile, handle : str ) -> str:
    subject = next( ( subject for subject in profile.subjects if subject.handle == handle ), None )
    return subject.name if subject is not None else handle


def _existing_roth_handle( profile, owner_handle : str ) -> Optional[ str ]:
    """The handle of a Roth account the owner already holds -- the first found, since a conversion
    needs no choice among several -- or None if they hold none."""
    roth = next( ( asset for asset in profile.assets
                   if asset.asset_class is AssetClass.ROTH and asset.owner_handle == owner_handle ),
                 None )
    return roth.handle if roth is not None else None


def _minted_roth_handle( profile, owner_handle : str ) -> str:
    """A fresh handle for a newly-provisioned Roth, unique among the profile's holdings (not
    assuming the owner's natural handle is free)."""
    taken  = { asset.handle for asset in profile.assets }
    base   = f'{_ROTH_HANDLE_PREFIX}{owner_handle}'
    handle = base
    suffix = 2
    while handle in taken:
        handle = f'{base}-{suffix}'
        suffix += 1
    return handle


def _ensure_roth_account( profile, owner_handle : str ):
    """The Roth account a conversion for `owner_handle` lands in -- the owner's existing one if they
    have any, otherwise a new empty Roth provisioned for them (the conversion implies it exists).
    Returns the (possibly updated) profile and the Roth's handle."""
    existing = _existing_roth_handle( profile, owner_handle )
    if existing is not None:
        return profile, existing
    handle  = _minted_roth_handle( profile, owner_handle )
    account = AssetProfile(
        handle = handle, name = f'{_subject_name( profile, owner_handle )} Roth',
        asset_class = AssetClass.ROTH, opening_value = Decimal( '0' ), owner_handle = owner_handle )
    return replace( profile, assets = list( profile.assets ) + [ account ] ), handle


def _names( profile ) -> dict:
    names = { subject.handle: subject.name for subject in profile.subjects }
    names.update( { asset.handle: asset.name for asset in profile.assets } )
    return names


def _money( amount ) -> str:
    return f'${amount:,.0f}' if amount is not None else ''


# --- The materialization accumulator --------------------------------------

class EventContributions:
    """The engine inputs a scenario's events contribute, bucketed by the `ForecastParameters` list
    each feeds; the materialization merges these into the parameters it assembles."""

    def __init__( self ):
        self.scheduled_events = list()
        self.income_items     = list()
        self.expense_items    = list()
        self.subject_removals = list()


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

    def cascade_on_add( self, event : PlanEvent, profile, scenario ):
        """Adjust other inputs when this event is added -- a sale ends its property's income and
        operating expenses at the sale date. Runs once, at add time (stateless and best-effort); the
        default changes nothing. Returns the (possibly updated) profile and scenario."""
        return profile, scenario

    def cascade_on_remove( self, event : PlanEvent, profile, scenario ):
        """Best-effort reverse of `cascade_on_add` when the event is removed."""
        return profile, scenario

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


class RothConversionEvent( EventType ):
    kind  = EventKind.ROTH_CONVERSION
    group = _ACCOUNTS_GROUP

    def references( self, profile ) -> list:
        return [ ReferenceSpec( SOURCE_ROLE, 'From pre-tax account', _pretax_accounts ) ]

    def provision( self, event : PlanEvent, profile ):
        """The conversion lands in the source owner's Roth -- found or created. The resolved Roth
        handle is recorded as the target selection, so materialization just reads it."""
        owner = _owner_of( profile, event.selections[ SOURCE_ROLE ] )
        profile, roth_handle = _ensure_roth_account( profile, owner )
        return profile, replace(
            event, selections = { **event.selections, TARGET_ROLE: roth_handle } )

    def summary( self, event : PlanEvent, profile ) -> str:
        source = _names( profile ).get( event.selections.get( SOURCE_ROLE ) )
        return f'Roth conversion of {_money( event.amount )} from {source}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.scheduled_events.append( ScheduledRealization(
            event_date = event.date, holding = event.selections[ SOURCE_ROLE ],
            amount = event.amount, destination = event.selections[ TARGET_ROLE ] ) )


class SellPropertyEvent( EventType ):
    kind       = EventKind.SELL_PROPERTY
    group      = _PROPERTY_GROUP
    has_amount = False   # the sale price is the projected value, not a user figure

    def references( self, profile ) -> list:
        return [ ReferenceSpec( PROPERTY_ROLE, 'Property', _properties ) ]

    def summary( self, event : PlanEvent, profile ) -> str:
        name   = _names( profile ).get( event.selections.get( PROPERTY_ROLE ) )
        notice = ( ' (mortgage payoff not yet modeled)'
                   if _has_mortgage( profile, event.selections.get( PROPERTY_ROLE ) ) else '' )
        return f'Sell {name} in {event.date.year}{notice}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        # No amount: a sale realizes the entire holding at its projected value.
        into.scheduled_events.append( ScheduledRealization(
            event_date = event.date, holding = event.selections[ PROPERTY_ROLE ] ) )

    def cascade_on_add( self, event : PlanEvent, profile, scenario ):
        return _end_property_flows(
            profile, scenario, event.selections[ PROPERTY_ROLE ], event.date )

    def cascade_on_remove( self, event : PlanEvent, profile, scenario ):
        return _reopen_property_flows(
            profile, scenario, event.selections[ PROPERTY_ROLE ], event.date )


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
    TransferEvent(), RothConversionEvent(), SellPropertyEvent(), TaxableReceiptEvent(),
    TaxFreeReceiptEvent(), GeneralPaymentEvent(), CharitablePaymentEvent(), MedicalPaymentEvent(),
    DeathEvent() )

_BY_KIND = { event_type.kind: event_type for event_type in _EVENT_TYPES }


def handler_for( kind : EventKind ) -> EventType:
    return _BY_KIND[ kind ]


def offerable_menu( profile ) -> list:
    """The offerable kinds, grouped in display order -- (group, [types]) for each non-empty
    group."""
    offerable = [ event_type for event_type in _EVENT_TYPES if event_type.offerable( profile ) ]
    grouped   = list()
    for group in _GROUP_ORDER:
        members = [ event_type for event_type in offerable if event_type.group == group ]
        if members:
            grouped.append( ( group, members ) )
    return grouped


def event_contributions( profile, scenario, subjects : dict ) -> EventContributions:
    """The engine inputs the scenario's events contribute. `subjects` maps a subject handle to the
    materialized engine `Subject` (an income event credits the recipient subject)."""
    into = EventContributions()
    for event in scenario.events:
        handler_for( event.kind ).contribute( event, profile, subjects, into )
    return into


# --- View/template context -------------------------------------------------

def menu_context( profile ) -> list:
    """The add menu for the templates: each group's offerable kinds as `{kind slug, label}`."""
    return [ { 'group': group,
               'types': [ { 'kind': event_type.kind.name.lower(), 'label': event_type.label }
                          for event_type in types ] }
             for group, types in offerable_menu( profile ) ]


def events_context( profile, scenario ) -> list:
    """The events list for the templates: each event's row index and human summary."""
    events = scenario.events if scenario is not None else list()
    return [ { 'index': index, 'summary': handler_for( event.kind ).summary( event, profile ) }
             for index, event in enumerate( events ) ]


# --- Forms ----------------------------------------------------------------

class EventForm( forms.Form ):
    """The add form for one event kind, built from its `EventType`: a date, an amount (when the
    kind carries one), and a picker per reference. A single candidate is shown pre-selected, so the
    user sees and confirms what the event acts on; more than one prepends a placeholder, so the user
    must choose (no silent default). `build_event` returns the `PlanEvent` to append."""

    date = forms.DateField( label = 'Date' )

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
    `EventAddView`/`EventDeleteView`, so Continue just advances. It exposes the current events and
    the offerable kinds for the pane."""

    def __init__( self, data = None, *, profile = None, scenario = None ):
        self._profile  = profile
        self._scenario = scenario

    def is_valid( self ) -> bool:
        return True

    @property
    def events( self ) -> list:
        return events_context( self._profile, self._scenario )

    @property
    def menu( self ) -> list:
        return menu_context( self._profile )

    def apply( self, profile, scenario ):
        return profile, scenario
