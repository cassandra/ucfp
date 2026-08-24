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
creates an implied entity the event needs, and *cascade* adjusts other inputs -- a home sale ending
its mortgage.)
"""
from dataclasses import dataclass, replace
from typing import Callable, Optional

from django import forms
from django.utils.text import slugify

from common.date_window import DateWindow
from common.forms import MoneyField
from common.recurrence import Duration, OneTime, Recurrence, TimeUnit
from common.schedule import Schedule

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.environment.constants import AppConst
from ucfp.forecast.parameters import (
    ExpenseItem, IncomeItem,
    ScheduledLoanPayoff, ScheduledPropertySale, ScheduledRealization, ScheduledTransfer, SubjectRemoval,
    WindowedAmount )
from ucfp.inputs.cadence import add_cadence_fields, cadence_cells, cadence_label, read_cadence
from ucfp.inputs.plans.enums import CreditCardPlanMode, EventKind, VehicleDispositionKind
from ucfp.inputs.plans.schemas import PlanEvent
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.vehicle_handles import vehicle_loan_handle
from ucfp.inputs.widgets import IsoDateInput
from ucfp.parameter_sets.enums import CadenceDomain


# Selection roles -- the canonical keys an event's references, the add form, and its materialization
# all agree on (each is a `PlanEvent.selections` key).
SUBJECT_ROLE   = 'subject'
RECIPIENT_ROLE = 'recipient'
SOURCE_ROLE    = 'source'
TARGET_ROLE    = 'target'
PROPERTY_ROLE   = 'property'
POSSESSION_ROLE = 'possession'
LOAN_ROLE       = 'loan'
CARD_ROLE       = 'card'

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


@dataclass( frozen = True )
class OptionSpec:
    """A non-entity setting an event kind offers, rendered as a checkbox and stored under `key` in the
    event's `options` ('yes' when checked, 'no' when not). Distinct from a `ReferenceSpec` (an entity
    choice); `default` is the initial checked state, `help_text` the note under it.

    `requires_residence` marks an option that applies only to selling the primary residence (see
    `SellPropertyEvent.options`): the add form shows it only while the chosen property is the residence
    and hides it otherwise. Cosmetic -- materialization already ignores such an option for a
    non-residence sale -- so the gate is a display convenience, not a correctness guard."""
    key                : str
    label              : str
    help_text          : str  = ''
    default            : bool = True
    requires_residence : bool = False


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


# Vehicles (DEPRECIATING) are deliberately excluded: a current vehicle's sale lives in its vehicle-plan
# disposition (Sell/Replace), so it has one home. This manual sale covers the other tangibles.
_POSSESSION_CLASSES = ( AssetClass.PRECIOUS_METALS, AssetClass.COLLECTIBLES )


def _possessions( profile ) -> list:
    """The tangible possessions a manual sale can sell -- precious metals and collectibles. A vehicle is
    sold through its vehicle-plan disposition instead, not here."""
    return [ ( asset.handle, asset.name ) for asset in profile.assets
             if asset.asset_class in _POSSESSION_CLASSES ]


def _rents_after_sale( event : PlanEvent ) -> bool:
    """Whether a residence sale converts the household to renting afterward -- the 'rent_after' option,
    defaulting to yes (you need somewhere to live). No means no housing footprint after the sale (housing
    provided, or modeled elsewhere), which is the clip-everything behavior."""
    return event.options.get( 'rent_after', 'yes' ) != 'no'


def _secured_loans( profile, asset_handle : str ) -> list:
    """The **account** handles of the loans secured by `asset_handle` -- the loans a sale of that asset
    pays off (a property's mortgage, a vehicle's auto loan). An asset may carry more than one, so this is a
    list. The handle is the account the engine holds, not the Debt's own identity: a vehicle's auto loan
    materializes vehicle-scoped (`vehicle-loan:{v}`), so a payoff resolves to the account, not `{v}-loan`."""
    return [ _loan_account_handle( debt ) for debt in profile.debts
             if debt.secured_asset == asset_handle ]


def _loan_account_handle( debt ) -> str:
    """The chart account handle a secured debt's loan materializes under: a vehicle auto loan is
    vehicle-scoped (`vehicle-loan:{v}`, keyed off the secured vehicle), every other secured loan keeps the
    Debt's own handle."""
    if debt.kind is DebtKind.AUTO and debt.secured_asset is not None:
        return vehicle_loan_handle( debt.secured_asset )
    return debt.handle


def _payoff_loan_handle( profile, debt_handle : str ) -> str:
    """The chart account handle a loan-payoff event targets: a debt by handle resolved to the account its
    loan materializes under (an auto loan's is vehicle-scoped), so the payoff finds the engine's account
    rather than the Debt's own identity. An unknown handle passes through (the engine skips a no-op)."""
    debt = next( ( d for d in profile.debts if d.handle == debt_handle ), None )
    return _loan_account_handle( debt ) if debt is not None else debt_handle


def _names( profile ) -> dict:
    names = { subject.handle: subject.name for subject in profile.subjects }
    names.update( { asset.handle: asset.name for asset in profile.assets } )
    names.update( { debt.handle: debt.name for debt in profile.debts } )
    return names


def _asset_classes( profile ) -> dict:
    """Each asset's class, keyed by its handle -- lets a transfer tell an appreciating holding (whose
    move out is a sale that realizes a gain) from a face-value account (a plain, no-tax move)."""
    return { asset.handle: asset.asset_class
             for asset in profile.assets if asset.handle is not None }


def _money( amount ) -> str:
    return f'${amount:,.0f}' if amount is not None else ''


# The general (non-deductible) Payment books to its own named expense account rather than an equity
# disbursement, so the money shows up in the expense column. Its account handle carries this base, so the
# run-table display placement recognizes it and rolls it under Miscellaneous (`display_placement`), the way
# a property expense's handle carries its kind. The deductible payments (charitable, medical) take no such
# handle -- they group under their own tax-class column instead.
PAYMENT_EXPENSE_HANDLE_BASE = 'payment'


def payment_expense_handle( name : str ) -> str:
    """The expense-account handle a Payment materializes under -- `payment:<slug>`, keyed off its label so
    same-label payments share one account (and one run-table line) while distinct labels each get their
    own. Minted here, recognized by its base in `display_placement`."""
    return f'{PAYMENT_EXPENSE_HANDLE_BASE}:{slugify( name )}'


# A recurrence-capable kind's add form offers a one-time/recurring toggle (a `js-switch` control) that
# reveals a date-based window: "every {interval} from {date} to {finish}". `_RECUR_ONCE`/`_RECUR_ON` are the
# toggle's values (the recurring case reveals the window fields); `_RECUR_PREFIX` namespaces the cadence
# magnitude/unit fields; the domain offers month/year (coarsest = year) seeded to a sensible yearly default.
_RECUR_ONCE     = 'once'
_RECUR_ON       = 'recurring'
_RECUR_PREFIX   = 'recur'
_RECUR_DOMAIN   = CadenceDomain.MO_YR
_RECUR_DEFAULT  = Duration( 1, TimeUnit.YEAR )


def _payment_cadence( event : PlanEvent ):
    """A payment's engine cadence: a single dated occurrence when one-time, else the repeating cadence.
    The engine expands the recurrence over the item's window (anchored at the window start), so a recurring
    payment rides the existing expense-expansion path with no engine change."""
    if event.interval is None:
        return OneTime( event.date )
    return Recurrence( event.interval )


def _payment_window( event : PlanEvent ) -> DateWindow:
    """A payment's existence window: unbounded for a one-time payment (its single date carries it), else the
    `[date, finish]` window its recurrence repeats across."""
    if event.interval is None:
        return DateWindow()
    return DateWindow( start = event.date, end = event.finish )


def _window_text( event : PlanEvent ) -> str:
    """A recurring payment's window for the chip -- "2032 to 2035", or "from 2032" when open-ended."""
    if event.finish is None:
        return f'from {event.date.year}'
    return f'{event.date.year} to {event.finish.year}'


def _fixed_suffix( event : PlanEvent ) -> str:
    """A chip marker for a payment fixed in nominal terms (not inflation-indexed) -- empty for the
    inflation-indexed default, so only the exception is called out."""
    return '' if event.inflation_indexed else ' (fixed)'


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
        self.possession_sales = dict()   # possession handle -> sale date, for clipping its running costs


# --- The handler base + the kinds -----------------------------------------

class EventType:
    """One kind of plan event. The common case is a single dated amount feeding one engine input;
    a subclass overrides only the references it needs, its summary, and how it contributes."""

    kind           : EventKind
    group          : str
    has_amount     : bool = True
    has_label      : bool = False   # whether the add form offers an optional free-text purpose (EventForm)
    has_recurrence : bool = False   # whether the add form offers the one-time/recurring toggle (EventForm)
    has_inflation  : bool = False   # whether the add form offers the "adjust for inflation" toggle
    editable       : bool = True    # whether an existing event of this kind can be edited in place
    description    : str  = ''   # a one-line "what this is", shown under the add form's title

    @property
    def label( self ) -> str:
        return self.kind.label

    def is_editable( self, event : PlanEvent, profile ) -> bool:
        """Whether this existing event can be edited in place -- an editable kind whose every referenced
        entity still exists. A kind marked not editable (a card payoff, managed elsewhere) never is; an
        event pointing at a since-removed entity is not (its drifted picker has no valid value to seed), so
        it is removed and re-added rather than edited."""
        return self.editable and self._references_resolvable( event, profile )

    def _references_resolvable( self, event : PlanEvent, profile ) -> bool:
        """Whether every entity this event references still exists among the current candidates -- False
        once a referenced account, property, or subject has been removed from the profile."""
        for spec in self.references( profile ):
            chosen = event.selections.get( spec.role )
            if chosen not in { handle for handle, _label in spec.choices( profile ) }:
                return False
        return True

    def references( self, profile ) -> list:
        return list()

    def options( self, profile ) -> list:
        """The non-entity settings (checkboxes) this kind offers, in reading order -- empty for most
        kinds. Each `OptionSpec`'s key is a `PlanEvent.options` key its `contribute` reads."""
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
        The default provisions nothing."""
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
    kind        = EventKind.TRANSFER
    group       = _ACCOUNTS_GROUP
    description = 'Move money between two of your accounts.'

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
        source       = event.selections[ SOURCE_ROLE ]
        target       = event.selections[ TARGET_ROLE ]
        classes      = _asset_classes( profile )
        source_class = classes.get( source )
        target_class = classes.get( target )
        # Moving out of an appreciating holding is a sale: realize the proportional embedded gain into
        # the source class's realized-gain income (a capital gain for stocks, an ordinary distribution
        # for a pre-tax account) rather than a no-tax value move. A face-value source (cash, CDs) has
        # no gain and takes the plain transfer below.
        realizes_gain = ( source_class is not None ) and source_class.accrues_unrealized_gains
        if realizes_gain:
            # Proceeds to the cash hub for a cash target, else a conversion into the target holding
            # (which re-establishes basis there).
            target_is_cash_hub = target_class is AssetClass.CASH
            into.scheduled_events.append( ScheduledRealization(
                event_date = event.date, holding = source, amount = event.amount,
                destination = None if target_is_cash_hub else target ) )
            return
        into.scheduled_events.append( ScheduledTransfer(
            event_date = event.date, source = source, target = target, amount = event.amount ) )


class SellPropertyEvent( EventType ):
    kind        = EventKind.SELL_PROPERTY
    group       = _PROPERTY_GROUP
    has_amount  = False   # the sale price is the projected value, not a user figure
    description = 'Sell a property at its projected value; any mortgage is paid from the proceeds.'

    def references( self, profile ) -> list:
        return [ ReferenceSpec( PROPERTY_ROLE, 'Property', _properties ) ]

    def options( self, profile ) -> list:
        # Offered only to a household that owns a home -- selling the primary residence makes them a
        # renter. Materialization applies it to the residence sale alone (a second-home/rental sale
        # ignores it), so it is inert if the chosen property is not the residence.
        if not any( a.asset_class is AssetClass.REAL_ESTATE_RESIDENCE for a in profile.assets ):
            return list()
        return [ OptionSpec(
            key                = 'rent_after',
            label              = 'Rent after selling your home',
            help_text          = 'When selling your primary residence, become a renter afterward -- '
                                 'utilities continue and rent begins from the sale. Uncheck if housing is '
                                 'provided or handled elsewhere.',
            default            = True,
            requires_residence = True ) ]   # shown only while the chosen property is the residence

    def summary( self, event : PlanEvent, profile ) -> str:
        handle = event.selections.get( PROPERTY_ROLE )
        name   = _names( profile ).get( handle ) or 'a removed property'    # may be gone (drift)
        notice = ' (mortgage paid off)' if _secured_loans( profile, handle ) else ''
        return f'Sell {name} in {event.date.year}{notice}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        # No amount: a sale realizes the entire holding at its projected value, then pays off any
        # mortgage secured by it from the proceeds (the engine clears the projected balance).
        property_handle = event.selections[ PROPERTY_ROLE ]
        into.property_sales[ property_handle ] = event.date
        # A thin sale trigger: the handle, the date, and the rent-after choice. The engine reaches the
        # property's `PropertyData` for the realize/costs/mortgage-payoff -- the same routine a shortfall
        # drawdown calls -- so no realize or payoff machinery is composed here.
        # The rent-after choice rides the trigger (the residence choice; moot for a non-residence sale) to
        # the engine, which reports the sale so the forecast reconfigures the residence's forward expenses --
        # ending its own costs, carrying its utilities, and opening rent -- however the sale is triggered.
        into.scheduled_events.append( ScheduledPropertySale(
            event_date = event.date, holding = property_handle, rent_after = _rents_after_sale( event ) ) )
        # A sale needs no income cascade: a rental's rent is clipped to the sale date at materialize
        # (`_clipped_to_sale`, from this event's `property_sales`), as are a non-residence property's
        # operating expenses. The residence's are books-driven, reconfigured by the forecast.


def _contribute_possession_sale( profile, possession_handle : str, sale_date, into : EventContributions ):
    """Sell a possession into `into`: realize the whole holding at its projected value (tax follows its
    asset class -- a vehicle is TAX_FREE, a collectible taxed as one), pay off any loan secured by it, and
    record the sale date so materialization ends its running costs at it (mirroring a property sale).
    Shared by the manual sell-possession event and the derived vehicle transition."""
    into.possession_sales[ possession_handle ] = sale_date
    into.scheduled_events.append( ScheduledRealization(
        event_date = sale_date, holding = possession_handle ) )
    for loan_handle in _secured_loans( profile, possession_handle ):
        into.scheduled_events.append( ScheduledLoanPayoff(
            event_date = sale_date, loan = loan_handle ) )


class SellPossessionEvent( EventType ):
    kind        = EventKind.SELL_POSSESSION
    group       = _PROPERTY_GROUP
    has_amount  = False   # a full sale at the possession's projected value, not a user figure
    description = 'Sell a possession at its projected value; any loan secured by it is paid off.'

    def references( self, profile ) -> list:
        return [ ReferenceSpec( POSSESSION_ROLE, 'Possession', _possessions ) ]

    def summary( self, event : PlanEvent, profile ) -> str:
        handle = event.selections.get( POSSESSION_ROLE )
        name   = _names( profile ).get( handle ) or 'a removed possession'  # may be gone (drift)
        notice = ' (loan paid off)' if _secured_loans( profile, handle ) else ''
        return f'Sell {name} in {event.date.year}{notice}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        _contribute_possession_sale( profile, event.selections[ POSSESSION_ROLE ], event.date, into )


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
    editable   = False   # managed in the Debt plan step; its LOAN_ROLE has no add-form picker to round-trip

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
            event_date = event.date, loan = _payoff_loan_handle( profile, event.selections[ LOAN_ROLE ] ) ) )


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
    editable   = False   # managed in the card paydown calculator (and carries a remove-cascade), not here

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
    kind        = EventKind.TAXABLE_RECEIPT
    group       = _MONEY_IN_GROUP
    description = 'A one-off taxable amount someone receives (taxed as ordinary income).'

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
            cadence = OneTime( event.date ), name = 'Taxable receipt' ) )


class TaxFreeReceiptEvent( EventType ):
    """A one-off tax-free amount received -- a gift, inheritance, or payout. It books as tax-free income (not
    an equity receipt), so the money shows up in the income column where a user looks for inflows; net worth
    rises by the same amount either way, and the tax-free class keeps it out of taxable income. The income
    is not attributed to a person (no recipient) -- a gift is the household's, and being tax-free its owner
    does not affect tax. This is the money-in mirror of the general Payment (visibility is orthogonal to
    taxability)."""

    kind        = EventKind.TAX_FREE_RECEIPT
    group       = _MONEY_IN_GROUP
    description = 'A one-off tax-free amount received -- a gift, inheritance, or payout.'

    def summary( self, event : PlanEvent, profile ) -> str:
        return f'Tax-free receipt of {_money( event.amount )} in {event.date.year}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        into.income_items.append( IncomeItem(
            subject = None, income_tax_class = IncomeTaxClass.TAX_FREE,
            amounts = Schedule.constant( WindowedAmount( event.amount ) ),
            cadence = OneTime( event.date ), name = 'Tax-free receipt' ) )


class _ExpensePaymentEvent( EventType ):
    """A payment out that books as a visible expense line -- the shared base of the general (non-deductible)
    and the deductible (charitable, medical) payments. All carry an optional purpose that names their
    account (so repeats of one kind collapse into a single run-table line), a date-based recurrence, and the
    inflation toggle; they differ only in their `expense_tax_class`, their wording, and -- for the general
    payment -- where the run table groups the account. No engine change: each materializes to an
    `ExpenseItem`, which the forecast already expands over its window."""

    group          = _MONEY_OUT_GROUP
    has_label      = True
    has_recurrence = True
    has_inflation  = True
    expense_tax_class : ExpenseTaxClass

    def summary( self, event : PlanEvent, profile ) -> str:
        money = _money( event.amount )
        if event.interval is None:
            schedule = f'in {event.date.year}'
        else:
            schedule = f'{cadence_label( event.interval )}, {_window_text( event )}'
        return f'{self._effective_label( event )} of {money} {schedule}{_fixed_suffix( event )}'

    def contribute( self, event : PlanEvent, profile, subjects : dict, into : EventContributions ):
        name = self._effective_label( event )
        into.expense_items.append( ExpenseItem(
            name = name, expense_tax_class = self.expense_tax_class,
            amounts = Schedule.constant( WindowedAmount( event.amount ) ),
            cadence = _payment_cadence( event ), window = _payment_window( event ),
            handle = self._account_handle( name ), inflate = event.inflation_indexed ) )

    def _effective_label( self, event : PlanEvent ) -> str:
        """The payment's purpose for its account name and chip -- the user's free-text label, or the kind's
        own name (e.g. "Charitable gift") when blank."""
        return event.label.strip() or self.label

    def _account_handle( self, name : str ):
        """The expense-account handle -- None by default, so a deductible payment falls to its own tax-class
        column in the run table. The general payment overrides this to route to Miscellaneous."""
        return None


class GeneralPaymentEvent( _ExpensePaymentEvent ):
    """A non-deductible payment out -- tuition, a wedding, a personal gift. It books as a plain LIVING
    expense (not an equity disbursement), so the money shows up in the expense column where a user looks for
    it; net worth falls by the same amount either way, with no tax effect. Its purpose names its own account
    under Miscellaneous, so repeated payments of one kind collapse into one run-table line."""

    kind              = EventKind.GENERAL_PAYMENT
    expense_tax_class = ExpenseTaxClass.LIVING
    description       = 'A payment out of the plan -- one-time, or repeating over a date window.'

    def _account_handle( self, name : str ):
        return payment_expense_handle( name )   # routes to the Miscellaneous rung (see display_placement)


class CharitablePaymentEvent( _ExpensePaymentEvent ):
    kind              = EventKind.CHARITABLE_PAYMENT
    expense_tax_class = ExpenseTaxClass.CHARITABLE
    description       = 'A charitable gift (tax-deductible) -- one-time, or repeating over a date window.'


class MedicalPaymentEvent( _ExpensePaymentEvent ):
    kind              = EventKind.MEDICAL_PAYMENT
    expense_tax_class = ExpenseTaxClass.MEDICAL
    description       = 'A medical expense (tax-deductible) -- one-time, or repeating over a date window.'


class DeathEvent( EventType ):
    kind        = EventKind.DEATH
    group       = _HOUSEHOLD_GROUP
    has_amount  = False
    description = "Project a household member's death to model its financial impact."

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
    TransferEvent(), SellPropertyEvent(), SellPossessionEvent(), LoanPayoffEvent(),
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


def vehicle_disposition_contributions( profile, plans, into : EventContributions ):
    """The sales a vehicle plan's dispositions imply: a complete SELL or REPLACE disposition sells that
    current vehicle (and pays off its loan, and ends its running costs) on the disposition date -- the
    automated twin of a hand-added sell-possession event, from the stored disposition rather than a
    written event. Only a complete disposition sells, so a half-entered REPLACE never strands the vehicle
    (sold with no replacement yet) -- it stays retained until finished. A REPLACE's successor purchase is
    materialized separately (as a plan vehicle); RETAIN sells nothing. A disposition for a vehicle the
    Profile no longer has is skipped, so a Profile edit degrades gracefully. (A current vehicle is a
    `DEPRECIATING` holding, so the same possession-sale helper realizes it.)"""
    plan = plans.vehicle_plan
    if plan is None:
        return
    asset_handles = { asset.handle for asset in profile.assets }
    for disposition in plan.dispositions:
        if disposition.kind is VehicleDispositionKind.KEEP or not disposition.is_complete:
            continue                                     # retained, or not yet fully entered
        if disposition.vehicle_handle not in asset_handles:
            continue                                     # a dropped vehicle
        _contribute_possession_sale( profile, disposition.vehicle_handle, disposition.sale_date, into )


# --- View/template context -------------------------------------------------

def menu_context( profile ) -> list:
    """The add menu for the templates: each group's offerable kinds as `{kind slug, label}`."""
    return [ { 'group': group,
               'types': [ { 'kind': event_type.kind.name.lower(), 'label': event_type.label }
                          for event_type in types ] }
             for group, types in offerable_menu( profile ) ]


def events_context( profile, plans ) -> list:
    """The events list for the templates: each event's row index, human summary, and whether it can be
    edited in place (the row shows an Edit affordance only when so)."""
    events = plans.events if plans is not None else list()
    rows   = list()
    for index, event in enumerate( events ):
        handler = handler_for( event.kind )
        rows.append( { 'index'    : index,
                       'summary'  : handler.summary( event, profile ),
                       'editable' : handler.is_editable( event, profile ) } )
    return rows


# --- Forms ----------------------------------------------------------------

@dataclass( frozen = True )
class BoundOption:
    """One option checkbox for the template: its bound `field` paired with whether it is residence-gated
    (shown only when the chosen property is the primary residence). Pairing the flag with the field here
    keeps the domain rule out of the template -- it renders the marker, not the logic."""
    field              : object
    requires_residence : bool


class EventForm( forms.Form ):
    """The add form for one event kind, built from its `EventType`: a picker per reference, an amount
    (when the kind carries one), and a date -- in that reading order. A single candidate is shown
    pre-selected, so the user sees and confirms what the event acts on; more than one prepends a
    placeholder, so the user must choose (no silent default). `build_event` returns the `PlanEvent`."""

    def __init__( self, data = None, *, event_type = None, profile = None, event = None ):
        super().__init__( data )
        self._event_type = event_type
        self._profile    = profile
        self._event      = event   # when editing, the event whose values seed the fields' initials
        # Order the form the way one describes an event: what it acts on, then how much, then when.
        for spec in event_type.references( profile ):
            self.fields[ self._role_field( spec.role ) ] = forms.ChoiceField(
                label = spec.label, choices = self._choices( spec.choices( profile ) ),
                initial = event.selections.get( spec.role ) if event else None,
                widget = forms.Select( attrs = { 'class' : 'custom-select' } ) )
        if event_type.has_label:
            # Optional: a free-text purpose that names the payment's expense account and its chip. The
            # placeholder shows the kind's own name, the value a blank label falls back to.
            self.fields[ 'label' ] = forms.CharField(
                label = 'Purpose', required = False, max_length = 60,
                initial = event.label if event else None,
                widget = forms.TextInput( attrs = { 'placeholder' : event_type.label } ) )
        if event_type.has_amount:
            self.fields[ 'amount' ] = MoneyField(
                label = 'Amount', min_value = 0, initial = event.amount if event else None )
        self.fields[ 'date' ] = forms.DateField(
            label = 'Date', initial = event.date if event else None, widget = IsoDateInput() )
        if event_type.has_recurrence:
            # A one-time/recurring toggle (a `js-switch` control): 'recurring' reveals the cadence + finish
            # date, turning the single `date` into the window start. The cadence is seeded to a yearly
            # default so toggling on reads "every 1 year"; the whole window is date-based. Editing a
            # recurring event opens on the recurring case with its own cadence and end date.
            self.fields[ 'recurring' ] = forms.ChoiceField(
                required = False, initial = _RECUR_ON if self._is_recurring_event() else _RECUR_ONCE,
                choices = [ ( _RECUR_ONCE, 'One-time' ), ( _RECUR_ON, 'Recurring' ) ],
                widget = forms.RadioSelect(
                    attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
            add_cadence_fields( self, _RECUR_PREFIX, self._seeded_interval(), _RECUR_DOMAIN )
            self.fields[ 'finish' ] = forms.DateField(
                label = 'Until', required = False, initial = event.finish if event else None,
                widget = IsoDateInput() )
        if event_type.has_inflation:
            # On by default: the amount is read as today's dollars and grown to nominal. Unchecked fixes it
            # in nominal terms (the entered figure is paid as-is each occurrence).
            self.fields[ 'inflation_indexed' ] = forms.BooleanField(
                label = 'Adjust for inflation', required = False,
                initial = event.inflation_indexed if event else True,
                help_text = "Amount is in today's dollars and grows with inflation; uncheck for a "
                            'fixed-dollar amount.',
                widget = forms.CheckboxInput( attrs = { 'class' : 'custom-control-input' } ) )
        for opt in event_type.options( profile ):
            self.fields[ self._option_field( opt.key ) ] = forms.BooleanField(
                label = opt.label, required = False, help_text = opt.help_text,
                initial = self._seeded_option( opt ),
                widget = forms.CheckboxInput( attrs = { 'class' : 'custom-control-input' } ) )

    def _is_recurring_event( self ) -> bool:
        return ( self._event is not None ) and ( self._event.interval is not None )

    def _seeded_interval( self ):
        """The cadence the recurrence fields seed from -- the edited event's interval when recurring, else
        the yearly default (so a fresh or one-time event opens on 'every 1 year' when toggled recurring)."""
        return self._event.interval if self._is_recurring_event() else _RECUR_DEFAULT

    def _seeded_option( self, opt ) -> bool:
        """An option checkbox's initial -- the edited event's stored choice ('yes'/'no'), else the kind's
        default for a fresh add."""
        if self._event is None:
            return opt.default
        return self._event.options.get( opt.key, 'yes' if opt.default else 'no' ) != 'no'

    @property
    def reference_fields( self ):
        """The reference pickers as bound fields, in order -- rendered as their own row, so the amount
        and date stay paired below them regardless of how many references a kind has."""
        return [ self[ self._role_field( spec.role ) ]
                 for spec in self._event_type.references( self._profile ) ]

    @property
    def label_field( self ):
        """The bound purpose field, or None for a kind that offers none -- rendered above the amount."""
        return self[ 'label' ] if 'label' in self.fields else None

    @property
    def amount_field( self ):
        """The bound amount field, or None for a kind that carries none."""
        return self[ 'amount' ] if 'amount' in self.fields else None

    @property
    def recurring_field( self ):
        """The bound one-time/recurring toggle, or None for a kind that does not recur -- the `js-switch`
        control whose value reveals the window fields."""
        return self[ 'recurring' ] if 'recurring' in self.fields else None

    @property
    def recurring_case( self ) -> str:
        """The toggle value the recurrence window is shown for -- the template marks the window block with
        it, so the switch reveals the block only when 'recurring' is chosen."""
        return _RECUR_ON

    @property
    def recurrence_cadence( self ) -> dict:
        """The bound cadence magnitude/unit fields (the "every N period" control) for the recurrence
        window, rendered inside the revealed case."""
        return cadence_cells( self, _RECUR_PREFIX, _RECUR_DEFAULT, _RECUR_DOMAIN )

    @property
    def finish_field( self ):
        """The bound recurrence-end date, or None for a kind that does not recur."""
        return self[ 'finish' ] if 'finish' in self.fields else None

    @property
    def inflation_field( self ):
        """The bound "adjust for inflation" checkbox, or None for a kind that does not offer it."""
        return self[ 'inflation_indexed' ] if 'inflation_indexed' in self.fields else None

    @property
    def option_fields( self ):
        """The kind's option checkboxes, in order (empty for most kinds) -- each a `BoundOption` pairing
        the bound field with its residence gate, rendered below the date."""
        return [ BoundOption( field = self[ self._option_field( opt.key ) ],
                              requires_residence = opt.requires_residence )
                 for opt in self._event_type.options( self._profile ) ]

    @property
    def gates_residence_option( self ) -> bool:
        """Whether the kind offers a residence-gated option -- so the template marks the form with the
        residence handles the property picker's value is matched against, to show or hide that option."""
        return any( opt.requires_residence for opt in self._event_type.options( self._profile ) )

    @property
    def residence_handles( self ) -> list:
        """The handle(s) of the profile's primary residence -- the values a residence-gated option is
        shown for (at most one, but treated as a set for safety). The property picker's value is checked
        against these client-side to reveal or hide such an option."""
        return [ asset.handle for asset in self._profile.assets
                 if asset.asset_class is AssetClass.REAL_ESTATE_RESIDENCE ]

    @staticmethod
    def _role_field( role : str ) -> str:
        return f'select_{role}'

    @staticmethod
    def _option_field( key : str ) -> str:
        return f'option_{key}'

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
        self._validate_recurrence( cleaned )
        return cleaned

    def _validate_recurrence( self, cleaned : dict ) -> None:
        """A recurring payment needs an end no earlier than its start; a one-time one ignores the window
        fields. (A blank cadence magnitude just falls back to the yearly default -- non-blocking.)"""
        if not self._is_recurring( cleaned ):
            return
        finish = cleaned.get( 'finish' )
        start  = cleaned.get( 'date' )
        if finish is None:
            self.add_error( 'finish', 'Give an end date for a recurring payment.' )
        elif ( start is not None ) and ( finish < start ):
            self.add_error( 'finish', 'The end date must not be before the start date.' )
        return

    def _is_recurring( self, cleaned : dict ) -> bool:
        return self._event_type.has_recurrence and ( cleaned.get( 'recurring' ) == _RECUR_ON )

    def _selections( self, cleaned : dict ) -> dict:
        return { spec.role: cleaned.get( self._role_field( spec.role ) )
                 for spec in self._event_type.references( self._profile ) }

    def build_event( self ) -> PlanEvent:
        interval, finish = self._recurrence( self.cleaned_data )
        return PlanEvent(
            kind = self._event_type.kind, date = self.cleaned_data[ 'date' ],
            amount = self.cleaned_data.get( 'amount' ),
            label = ( self.cleaned_data.get( 'label' ) or '' ).strip(),
            interval = interval, finish = finish,
            inflation_indexed = self._inflation_indexed( self.cleaned_data ),
            selections = self._selections( self.cleaned_data ),
            options = self._options( self.cleaned_data ) )

    def _inflation_indexed( self, cleaned : dict ) -> bool:
        """Whether the payment is inflation-indexed -- the checkbox when the kind offers it (on by default),
        else True (the model-wide default; a kind without the toggle indexes as everything else does)."""
        if not self._event_type.has_inflation:
            return True
        return bool( cleaned.get( 'inflation_indexed' ) )

    def _recurrence( self, cleaned : dict ) -> tuple:
        """The event's recurrence as `(interval, finish)` -- `(None, None)` for a one-time payment (the
        toggle off, or a kind that does not recur), else the chosen cadence over its end date."""
        if not self._is_recurring( cleaned ):
            return None, None
        return read_cadence( self, _RECUR_PREFIX, _RECUR_DEFAULT, _RECUR_DOMAIN ), cleaned.get( 'finish' )

    def _options( self, cleaned : dict ) -> dict:
        return { opt.key: ( 'yes' if cleaned.get( self._option_field( opt.key ) ) else 'no' )
                 for opt in self._event_type.options( self._profile ) }


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
