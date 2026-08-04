"""§ Vehicle Expenses -- the household's cars as a per-vehicle list.

Each car is a `Vehicle` on the `VehiclePlan`, entered as a unit (name, next purchase date, price,
replacement interval, an optional owned-until date, and optional financing) -- the vehicle mirror of a
mortgaged property. This module owns minting, editing, and removing a vehicle; the shared per-car
running costs are a sibling pane (`vehicle_expenses.py`). Non-blocking: a vehicle materializes only
once its required fields are set, so a just-opened blank that is abandoned never appears.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField, StyledFormMixin

from ucfp.inputs.plans.schemas import Vehicle, VehiclePlan
from ucfp.inputs.vehicle_expenses import plan_has_content, vehicle_plan_of
from ucfp.inputs.widgets import IsoDateInput


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
    """Each vehicle for the list template: its handle, name, and a short plan summary."""
    return [ { 'handle': vehicle.handle, 'name': vehicle.name or 'Car', 'summary': _summary( vehicle ) }
             for vehicle in _vehicles( plans ) ]


def _summary( vehicle ) -> str:
    """A one-line description of a vehicle's plan -- price, replacement interval, and ownership span."""
    parts = list()
    if vehicle.purchase_price is not None:
        parts.append( f'${vehicle.purchase_price:,.0f}' )
    if vehicle.recurrence_years:
        parts.append( f'every {vehicle.recurrence_years} yr' )
    if vehicle.purchase_date is not None:
        span = f'from {vehicle.purchase_date.year}'
        if vehicle.end_date is not None:
            span += f' to {vehicle.end_date.year}'
        parts.append( span )
    return ' · '.join( parts )


def delete_vehicle( plans, handle : str ):
    """Remove one vehicle from the plan, collapsing the plan to None if nothing is left to persist."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return plans
    kept = replace( plan, vehicles = [ v for v in plan.vehicles if v.handle != handle ] )
    return replace( plans, vehicle_plan = kept if plan_has_content( kept ) else None )


class VehicleForm( StyledFormMixin, forms.Form ):
    """The add/edit form for one vehicle. Add and edit converge on a known handle (add mints one), so a
    new vehicle has a stable identity from the first keystroke. Fields are individually optional and the
    form background-saves; the vehicle materializes onto the plan only once all of `_REQUIRED` are set
    (`_complete`), so a partial or abandoned entry writes nothing. `apply` upserts the vehicle by handle,
    carrying the plan's shared running costs and other vehicles."""

    _REQUIRED = ( 'name', 'purchase_date', 'purchase_price', 'recurrence_years' )

    name             = forms.CharField( label = 'Name', max_length = 100, required = False )
    purchase_date    = forms.DateField(
        label = 'Next purchase date', required = False, widget = IsoDateInput() )
    purchase_price   = MoneyField( label = 'Price per car', min_value = 0, required = False )
    recurrence_years = forms.IntegerField(
        label = 'Replace every (years)', min_value = 1, required = False )
    end_date         = forms.DateField(
        label = 'Stop replacing by', required = False, widget = IsoDateInput(),
        help_text = 'Blank to keep replacing indefinitely.' )
    down_payment     = MoneyField( label = 'Down payment', min_value = 0, required = False )
    monthly_payment  = MoneyField( label = 'Monthly payment', min_value = 0, required = False )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
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
                 'end_date': vehicle.end_date, 'down_payment': vehicle.down_payment,
                 'monthly_payment': vehicle.monthly_payment }

    @staticmethod
    def _defaults( handle : str ) -> dict:
        """A fresh vehicle's seeded typicals -- a slot-numbered name plus a typical price and replacement
        interval -- with the next-purchase date left blank. The date is the one genuinely personal input,
        and its absence keeps a defaulted-but-untouched vehicle from materializing until the user sets it."""
        number = handle.rsplit( '-', 1 )[ -1 ]
        return { 'name': f'Vehicle {number}', 'purchase_price': Decimal( '35000' ),
                 'recurrence_years': 7 }

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
        vehicle  = Vehicle(
            handle = handle, name = cleaned[ 'name' ], purchase_date = cleaned[ 'purchase_date' ],
            end_date = cleaned.get( 'end_date' ), purchase_price = cleaned[ 'purchase_price' ],
            recurrence_years = cleaned[ 'recurrence_years' ],
            down_payment = cleaned.get( 'down_payment' ),
            monthly_payment = cleaned.get( 'monthly_payment' ) )
        existing = vehicle_plan_of( plans ) or VehiclePlan()
        kept     = [ v for v in existing.vehicles if v.handle != handle ] + [ vehicle ]
        return profile, replace( plans, vehicle_plan = replace( existing, vehicles = kept ) )
