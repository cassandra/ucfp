"""The per-current-vehicle disposition editor of the Vehicle plan step.

The vehicle plan is Profile-driven, mirroring the Debt plan: it solicits, for each current vehicle the
household owns (the DEPRECIATING holdings the Vehicles section entered), what to do with it -- Retain it
(the default -- hold it to the end of its life), Sell it on a date, or Replace it on a date with a
recurring purchase. Each choice is a `VehicleDisposition` keyed to the current vehicle's handle; Retain
is stored as the absence of one (so an untouched vehicle is never dangling). A Replace's successor reuses
the shared vehicle-purchase fields (`VehiclePurchaseForm`); net-new future vehicles are a separate list
(`vehicle.py`). This module owns listing the current vehicles and editing one's disposition.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.enums import LeaseDispositionKind, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LeasedVehicleDisposition, Vehicle, VehicleDisposition, VehiclePlan )
from ucfp.inputs.vehicle import VehiclePurchaseForm
from ucfp.inputs.vehicle_expenses import plan_has_content, vehicle_plan_of
from ucfp.inputs.widgets import IsoDateInput


def _current_vehicles( profile ) -> list:
    """The household's current vehicles -- the DEPRECIATING holdings the Vehicles (Profile) section
    entered, the entities the disposition list is driven by."""
    if profile is None:
        return list()
    return [ asset for asset in profile.assets if asset.asset_class is AssetClass.DEPRECIATING ]


def _disposition_for( plans, handle : str ):
    """The stored disposition for a current vehicle, or None (meaning Retain -- the default)."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return None
    return next( ( d for d in plan.dispositions if d.vehicle_handle == handle ), None )


def dispositions_context( profile, plans ) -> list:
    """One row per current vehicle for the disposition list -- its handle, name, and a summary of its
    current disposition (Retain by default)."""
    return [ { 'handle' : asset.handle, 'name' : asset.name,
               'summary' : _summary( _disposition_for( plans, asset.handle ) ) }
             for asset in _current_vehicles( profile ) ]


def _summary( disposition ) -> str:
    """A current vehicle's disposition in a phrase -- 'Retain' when none is stored, else the kind and, if
    dated, the year it happens."""
    if disposition is None:
        return VehicleDispositionKind.KEEP.label                 # 'Retain'
    if disposition.sale_date is None:
        return disposition.kind.label
    return f'{disposition.kind.label} in {disposition.sale_date.year}'


class VehicleDispositionForm( VehiclePurchaseForm ):
    """The disposition editor for one current vehicle: Retain it (the default), Sell it on a date, or
    Replace it on a date with a recurring purchase (whose fields are the inherited vehicle-purchase ones).
    Keyed to the current vehicle by `handle`. Non-blocking and background-saved: the chosen kind is
    recorded immediately (Retain stores nothing -- it is the default), and materialization emits the sale
    and the replacement only once their date and fields are set. The `kind` radio is the outer switch that
    reveals the date (Sell/Replace) and the replacement fields (Replace); the payment method is a nested
    switch within."""

    kind = forms.ChoiceField(
        label = 'Plan for this vehicle', required = False,
        choices = [ ( k.name, k.label ) for k in VehicleDispositionKind ],
        initial = VehicleDispositionKind.KEEP.name,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    sale_date = forms.DateField( label = 'Sell or replace on', required = False, widget = IsoDateInput() )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        self._handle  = handle
        self._profile = profile
        super().__init__( data, initial = self._initial( plans, handle ) if handle else None )

    @staticmethod
    def _initial( plans, handle : str ) -> dict:
        disposition = _disposition_for( plans, handle )
        if disposition is None:
            return { 'kind' : VehicleDispositionKind.KEEP.name }   # default Retain
        initial = { 'kind' : disposition.kind.name, 'sale_date' : disposition.sale_date }
        car = disposition.replacement
        if car is not None:
            initial.update( {
                'purchase_price' : car.purchase_price, 'recurrence_years' : car.recurrence_years,
                'end_date' : car.end_date, 'payment_method' : car.payment_method.name,
                'down_payment' : car.down_payment, 'monthly_payment' : car.monthly_payment,
                'lease_end_payment' : car.lease_end_payment } )
        return initial

    # The kind-switch case values, so the template carries no member-name literals (mirrors the payment
    # switch's `payment_field_methods` etc.).
    @property
    def dated_kinds( self ) -> str:
        """The kinds that need a handover date -- Sell and Replace (Retain needs none)."""
        return f'{VehicleDispositionKind.SELL.name} {VehicleDispositionKind.REPLACE.name}'

    @property
    def replace_kind( self ) -> str:
        """The one kind that buys a replacement -- its case value reveals the replacement fields."""
        return VehicleDispositionKind.REPLACE.name

    def apply( self, profile, plans ):
        cleaned     = self.cleaned_data
        kind        = VehicleDispositionKind[ cleaned.get( 'kind' ) or VehicleDispositionKind.KEEP.name ]
        plan        = vehicle_plan_of( plans ) or VehiclePlan()
        others      = [ d for d in plan.dispositions if d.vehicle_handle != self._handle ]
        disposition = self._disposition( kind, cleaned )
        kept        = others + ( [ disposition ] if disposition is not None else [] )
        plan        = replace( plan, dispositions = kept )
        return profile, replace( plans, vehicle_plan = plan if plan_has_content( plan ) else None )

    def _disposition( self, kind, cleaned ):
        # Retain is the default, so it is stored as the absence of a disposition (nothing to persist).
        if kind is VehicleDispositionKind.KEEP:
            return None
        replacement = self._replacement( cleaned ) if kind is VehicleDispositionKind.REPLACE else None
        return VehicleDisposition( vehicle_handle = self._handle, kind = kind,
                                   sale_date = cleaned.get( 'sale_date' ), replacement = replacement )

    def _replacement( self, cleaned ) -> Vehicle:
        # The successor's identity and first-purchase date are supplied at materialization from the
        # disposition (handle derived from the current vehicle, purchase date the handover date), so they
        # are left unset here; the name carries the current vehicle's for the run table.
        return Vehicle( handle = '', name = self._current_name(), purchase_date = None,
                        **self._purchase_spec( cleaned ) )

    def _current_name( self ) -> str:
        asset = next( ( a for a in _current_vehicles( self._profile ) if a.handle == self._handle ), None )
        return asset.name if asset is not None else ''


# --- Leased vehicles ------------------------------------------------------

def _leased_disposition_for( plans, handle : str ):
    """The stored leased disposition for a current lease, or None (meaning the default -- Return)."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return None
    return next( ( d for d in plan.leased_dispositions if d.vehicle_handle == handle ), None )


def leased_dispositions_context( profile, plans ) -> list:
    """One row per current leased vehicle for the disposition list -- its handle, name, and a summary of
    its end-of-term plan (Return by default)."""
    leased = profile.leased_vehicles if profile is not None else list()
    return [ { 'handle' : vehicle.handle, 'name' : vehicle.name,
               'summary' : _leased_summary( _leased_disposition_for( plans, vehicle.handle ) ) }
             for vehicle in leased ]


def _leased_summary( disposition ) -> str:
    """A leased vehicle's plan in a phrase -- 'Return' when none is stored, else the kind and, if dated,
    the year the lease ends."""
    if disposition is None:
        return LeaseDispositionKind.RETURN.label                 # 'Return'
    if disposition.lease_end is None:
        return disposition.kind.label
    return f'{disposition.kind.label} in {disposition.lease_end.year}'


def all_dispositions_context( profile, plans ) -> list:
    """One row per current vehicle -- owned then leased -- for the single disposition list: each with its
    handle, name, ownership label, disposition summary, and the edit route its Edit opens (the owned and
    leased editors are separate but share one form area)."""
    owned = [ { **row, 'ownership': 'Owned', 'edit_route': 'vehicle_disposition_edit' }
              for row in dispositions_context( profile, plans ) ]
    leased = [ { **row, 'ownership': 'Leased', 'edit_route': 'leased_disposition_edit' }
               for row in leased_dispositions_context( profile, plans ) ]
    return owned + leased


class LeasedVehicleDispositionForm( VehiclePurchaseForm ):
    """The disposition editor for one current leased vehicle: its current lease terms (monthly, end) and
    what happens at term end -- Return (let it expire), Renew (keep leasing -- the monthly continues), or
    Buy (purchase a vehicle then, whose fields are the inherited purchase ones). Keyed to the leased
    vehicle by `handle`. Non-blocking and background-saved: the choice is recorded immediately (a bare
    Return stores nothing -- it is the default), and the lease and its successor materialize once their
    fields are set. The `kind` radio is the outer switch that reveals the Buy successor; the payment
    method is a nested switch within it."""

    kind = forms.ChoiceField(
        label = 'At lease end', required = False,
        choices = [ ( k.name, k.label ) for k in LeaseDispositionKind ],
        initial = LeaseDispositionKind.RETURN.name,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    monthly   = MoneyField( label = 'Monthly lease payment', min_value = 0, required = False )
    lease_end = forms.DateField( label = 'Lease ends', required = False, widget = IsoDateInput() )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        self._handle  = handle
        self._profile = profile
        super().__init__( data, initial = self._initial( plans, handle ) if handle else None )

    @staticmethod
    def _initial( plans, handle : str ) -> dict:
        disposition = _leased_disposition_for( plans, handle )
        if disposition is None:
            return { 'kind' : LeaseDispositionKind.RETURN.name }   # default Return
        initial = { 'kind' : disposition.kind.name, 'monthly' : disposition.monthly,
                    'lease_end' : disposition.lease_end }
        car = disposition.successor
        if car is not None:
            initial.update( {
                'purchase_price' : car.purchase_price, 'recurrence_years' : car.recurrence_years,
                'end_date' : car.end_date, 'payment_method' : car.payment_method.name,
                'down_payment' : car.down_payment, 'monthly_payment' : car.monthly_payment,
                'lease_end_payment' : car.lease_end_payment } )
        return initial

    @property
    def buy_kind( self ) -> str:
        """The one kind that buys a successor -- its case value reveals the purchase fields."""
        return LeaseDispositionKind.BUY.name

    def apply( self, profile, plans ):
        cleaned     = self.cleaned_data
        kind        = LeaseDispositionKind[ cleaned.get( 'kind' ) or LeaseDispositionKind.RETURN.name ]
        plan        = vehicle_plan_of( plans ) or VehiclePlan()
        others      = [ d for d in plan.leased_dispositions if d.vehicle_handle != self._handle ]
        disposition = self._disposition( kind, cleaned )
        kept        = others + ( [ disposition ] if disposition is not None else [] )
        plan        = replace( plan, leased_dispositions = kept )
        return profile, replace( plans, vehicle_plan = plan if plan_has_content( plan ) else None )

    def _disposition( self, kind, cleaned ):
        # A bare Return (the default, no terms entered) stores nothing; any chosen kind or entered lease
        # term is recorded so the current lease's cost (and successor) can materialize.
        monthly, lease_end = cleaned.get( 'monthly' ), cleaned.get( 'lease_end' )
        if kind is LeaseDispositionKind.RETURN and monthly is None and lease_end is None:
            return None
        successor = self._successor( cleaned ) if kind is LeaseDispositionKind.BUY else None
        return LeasedVehicleDisposition( vehicle_handle = self._handle, monthly = monthly,
                                         lease_end = lease_end, kind = kind, successor = successor )

    def _successor( self, cleaned ) -> Vehicle:
        # The bought vehicle's identity and first-purchase date are supplied at materialization from the
        # disposition (handle derived from the lease, purchase date the lease end); the name carries the
        # leased vehicle's for the run table.
        return Vehicle( handle = '', name = self._leased_name(), purchase_date = None,
                        **self._purchase_spec( cleaned ) )

    def _leased_name( self ) -> str:
        leased = self._profile.leased_vehicles if self._profile is not None else list()
        vehicle = next( ( v for v in leased if v.handle == self._handle ), None )
        return vehicle.name if vehicle is not None else ''
