"""The Vehicle plan step's net-new future vehicles -- the cars the household adds that are not tied to
one it owns or leases today (those are the per-current-vehicle dispositions in `vehicle_disposition.py`).

Each is a `Vehicle` on the `VehiclePlan`, entered as a unit (name, next purchase date, price, replacement
interval, an optional owned-until date, and optional financing) -- the vehicle mirror of a mortgaged
property, sharing its purchase fields with a disposition's replacement via `VehiclePurchaseForm`. This
module owns minting, editing, and removing such a vehicle; the shared per-car running costs are a sibling
pane (`vehicle_expenses.py`). Non-blocking: a vehicle materializes only once its required fields are set,
so a just-opened blank that is abandoned never appears.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField, StyledFormMixin

from ucfp.environment.constants import AppConst
from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.plans.enums import PaymentMethod
from ucfp.inputs.plans.schemas import Vehicle, VehiclePlan
from ucfp.inputs.vehicle_expenses import plan_has_content, vehicle_plan_of
from ucfp.inputs.widgets import IsoDateInput


# A fresh vehicle's seeded typicals -- the values a new row starts from, which the user then adjusts.
# These are UI seeds (what the form suggests); the auto-loan APR and term are engine assumptions read
# from BUILTIN_ASSUMPTIONS instead (see the `auto_loan_*` properties and materialization).
_TYPICAL_PRICE             = Decimal( '35000' )   # a mid-market new car
_TYPICAL_REPLACEMENT_YEARS = 7


def _vehicles( plans ) -> list:
    """The plan's vehicles, or an empty list when there is no plan yet."""
    plan = vehicle_plan_of( plans )
    return list( plan.vehicles ) if plan is not None else []


def _minted_vehicle_handle( plans ) -> str:
    """A fresh `vehicle-N` handle, the lowest index free among the plan's vehicles."""
    taken = { vehicle.handle for vehicle in _vehicles( plans ) }
    index = 1
    while f'vehicle-{index}' in taken:
        index += 1
    return f'vehicle-{index}'


def vehicles_context( plans ) -> list:
    """Each vehicle for the list template: its handle, name, a two-line summary, and whether it is
    incomplete (still missing the fields it needs to materialize, so it does not yet affect the
    projection). The headline (price and replacement interval) is the plan's shape; the detail (ownership
    span and -- least prominent -- the payment method) sits muted below."""
    return [ { 'handle': vehicle.handle, 'name': vehicle.name or 'Car',
               'headline': _headline_summary( vehicle ), 'detail': _detail_summary( vehicle ),
               'incomplete': not vehicle.is_materializable }
             for vehicle in _vehicles( plans ) ]


def _headline_summary( vehicle ) -> str:
    """The headline facts shown beside the name -- price and replacement interval."""
    parts = list()
    if vehicle.purchase_price is not None:
        parts.append( f'${vehicle.purchase_price:,.0f}' )
    if vehicle.recurrence_years:
        parts.append( f'every {vehicle.recurrence_years} yr' )
    return ' · '.join( parts )


def _detail_summary( vehicle ) -> str:
    """The secondary facts, muted below the headline -- the ownership span and the payment method (a
    minor attribute, so it trails here rather than leading)."""
    parts = list()
    if vehicle.purchase_date is not None:
        if vehicle.end_date is not None:
            parts.append( f'{vehicle.purchase_date.year}–{vehicle.end_date.year}' )   # en dash range
        else:
            parts.append( f'from {vehicle.purchase_date.year}' )
    parts.append( vehicle.payment_method.label )
    return ' · '.join( parts )


def delete_vehicle( plans, handle : str ):
    """Remove one vehicle from the plan, collapsing the plan to None if nothing is left to persist."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return plans
    kept = replace( plan, vehicles = [ v for v in plan.vehicles if v.handle != handle ] )
    return replace( plans, vehicle_plan = kept if plan_has_content( kept ) else None )


class VehiclePurchaseForm( StyledFormMixin, forms.Form ):
    """The shared fields and behavior of a recurring vehicle purchase: its price, replacement interval,
    ownership end, and payment method with its per-method fields -- the part a net-new vehicle and a
    Replace disposition's successor (`VehicleDispositionForm`) have in common. A subclass supplies when
    and how the purchase happens: a net-new vehicle its own next-purchase date and name, a disposition
    those from the current vehicle it replaces. The payment method drives which cost fields show (via the
    switch control) and how the forecast models each purchase."""

    purchase_price   = MoneyField(
        label = 'Price per vehicle', min_value = 0, required = False, css_class = AppConst.VEHICLE_PRICE_CLASS )
    recurrence_years = forms.IntegerField(
        label = 'Replace every (years)', min_value = 1, required = False,
        widget = forms.NumberInput( attrs = { 'class' : 'input-count' } ) )   # a year count, a digit or two
    end_date         = forms.DateField(
        label = 'Stop replacing by', required = False, widget = IsoDateInput(),
        help_text = 'Blank = no end.' )
    # `monthly_payment` serves loan and lease; `lease_end_payment` is the lease's turn-in cost.
    # `down_payment` serves both too, but its label differs by method (a loan's "Down payment" vs a
    # lease's "Due at signing"), so it carries no baked-in label -- the template renders the two
    # conditionally by the same switch (see `_vehicle_payment_fields.html`).
    payment_method   = forms.ChoiceField(
        label = 'Paying by', required = False,
        choices = [ ( method.name, method.label ) for method in PaymentMethod ],
        initial = PaymentMethod.CASH.name,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    down_payment      = MoneyField(
        label = '', min_value = 0, required = False,           # labelled conditionally in the template
        css_class = AppConst.VEHICLE_DOWN_CLASS )
    monthly_payment   = MoneyField(
        label = 'Monthly payment', min_value = 0, required = False,
        css_class = AppConst.VEHICLE_MONTHLY_CLASS )
    lease_end_payment = MoneyField( label = 'Due at end', min_value = 0, required = False )

    @property
    def auto_loan_apr_percent( self ) -> float:
        """The assumed auto-loan APR as a percent -- shown in the loan note and carried to the client
        calculator on the form, from the same `BUILTIN_ASSUMPTIONS` value materialization resolves at, so
        the estimate and the forecast agree."""
        return float( BUILTIN_ASSUMPTIONS.auto_loan_apr.fraction * 100 )

    @property
    def auto_loan_term_years( self ) -> int:
        return BUILTIN_ASSUMPTIONS.auto_loan_term_years

    @property
    def auto_loan_term_months( self ) -> int:
        """The assumed auto-loan term in months -- the unit the client amortization mirror works in."""
        return BUILTIN_ASSUMPTIONS.auto_loan_term_months

    # The switch's case values, derived from PaymentMethod so the template need not spell the member
    # names (which are the radio values too). The domain vocabulary stays here; the switch/JS read it
    # through the rendered `data-switch-case` and the finances marker, never as a literal.
    @property
    def purchase_methods( self ) -> str:
        """The methods that buy the car at a price -- cash or loan (a lease has no purchase price, so its
        price field is hidden)."""
        return f'{PaymentMethod.CASH.name} {PaymentMethod.LOAN.name}'

    @property
    def payment_field_methods( self ) -> str:
        """The methods whose down/monthly fields show -- a loan or a lease (cash pays none)."""
        return f'{PaymentMethod.LOAN.name} {PaymentMethod.LEASE.name}'

    @property
    def lease_only_method( self ) -> str:
        """The lease-only case -- a lease -- used for the lease-end field and the lease's "Due at signing"
        label (its switch-case value)."""
        return PaymentMethod.LEASE.name

    @property
    def financing_method( self ) -> str:
        """The one method that finances -- a loan -- singled out in the template wherever the loan case is
        (keeping the method name out of the JS): its radio is marked so the calculator fills the monthly,
        the loan note shows for it, and the down field is labelled "Down payment" for it (its switch-case
        value)."""
        return PaymentMethod.LOAN.name

    def _purchase_spec( self, cleaned ) -> dict:
        """The shared `Vehicle` purchase fields read from this form -- identity, next-purchase date, and
        name are the subclass's to supply around these."""
        method = cleaned.get( 'payment_method' ) or PaymentMethod.CASH.name
        return { 'purchase_price'    : cleaned.get( 'purchase_price' ),
                 'recurrence_years'  : cleaned.get( 'recurrence_years' ),
                 'end_date'          : cleaned.get( 'end_date' ),
                 'payment_method'    : PaymentMethod[ method ],
                 'down_payment'      : cleaned.get( 'down_payment' ),
                 'monthly_payment'   : cleaned.get( 'monthly_payment' ),
                 'lease_end_payment' : cleaned.get( 'lease_end_payment' ) }


class VehicleForm( VehiclePurchaseForm ):
    """The add/edit form for one net-new vehicle. Add and edit converge on a known handle (add mints one),
    so a new vehicle has a stable identity from the first keystroke. Fields are individually optional and
    the form background-saves; the vehicle materializes onto the plan only once all of `_REQUIRED` are set
    (`_complete`), so a partial or abandoned entry writes nothing. `apply` upserts the vehicle by handle,
    carrying the plan's shared running costs and other vehicles."""

    _REQUIRED = ( 'name', 'purchase_date', 'purchase_price', 'recurrence_years' )

    name          = forms.CharField( label = 'Name', max_length = 100, required = False )
    purchase_date = forms.DateField(
        label = 'Next purchase date', required = False, widget = IsoDateInput() )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        # `profile` is unused here (a net-new vehicle has no link to a current one -- that is the
        # per-vehicle disposition's job); it is accepted so every plan-vehicle form shares one signature.
        super().__init__( data, initial = self._initial( plans, handle ) if handle else None )
        self._handle = handle

    def clean( self ):
        # An owned-until date before the purchase date is an inverted ownership window: materialization
        # would silently emit nothing for the car, so surface it as a field error rather than a no-op.
        cleaned  = super().clean()
        purchase = cleaned.get( 'purchase_date' )
        end      = cleaned.get( 'end_date' )
        if ( purchase is not None ) and ( end is not None ) and ( end < purchase ):
            self.add_error( 'end_date', 'Owned-until date must be on or after the purchase date.' )
        return cleaned

    @classmethod
    def _initial( cls, plans, handle : str ) -> dict:
        vehicle = next( ( v for v in _vehicles( plans ) if v.handle == handle ), None )
        if vehicle is None:
            return cls._defaults( handle )
        return { 'name': vehicle.name, 'purchase_date': vehicle.purchase_date,
                 'purchase_price': vehicle.purchase_price, 'recurrence_years': vehicle.recurrence_years,
                 'end_date': vehicle.end_date, 'payment_method': vehicle.payment_method.name,
                 'down_payment': vehicle.down_payment, 'monthly_payment': vehicle.monthly_payment,
                 'lease_end_payment': vehicle.lease_end_payment }

    @staticmethod
    def _defaults( handle : str ) -> dict:
        """A fresh vehicle's seeded typicals -- a slot-numbered name, a typical price and replacement
        interval, and a cash purchase -- with the next-purchase date left blank. The date is the one
        genuinely personal input, and its absence keeps a defaulted-but-untouched vehicle from
        materializing until the user sets it."""
        number = handle.rsplit( '-', 1 )[ -1 ]
        return { 'name': f'Vehicle {number}', 'purchase_price': _TYPICAL_PRICE,
                 'recurrence_years': _TYPICAL_REPLACEMENT_YEARS,
                 'payment_method': PaymentMethod.CASH.name }

    def _complete( self ) -> bool:
        """All the fields a vehicle needs to materialize are present. No hard validation -- a partial
        vehicle is simply not written rather than fighting a background save."""
        cleaned = self.cleaned_data
        return all( cleaned.get( field ) not in ( None, '' ) for field in self._REQUIRED )

    def apply( self, profile, plans ):
        # Non-blocking and non-destructive: a partial edit writes nothing and leaves existing vehicles
        # untouched. Removal is the explicit delete action's job, not a side effect of incompleteness.
        if not self._complete():
            return profile, plans
        handle   = self._handle or _minted_vehicle_handle( plans )
        cleaned  = self.cleaned_data
        vehicle  = Vehicle( handle = handle, name = cleaned[ 'name' ],
                            purchase_date = cleaned[ 'purchase_date' ], **self._purchase_spec( cleaned ) )
        existing = vehicle_plan_of( plans ) or VehiclePlan()
        kept     = [ v for v in existing.vehicles if v.handle != handle ] + [ vehicle ]
        return profile, replace( plans, vehicle_plan = replace( existing, vehicles = kept ) )
