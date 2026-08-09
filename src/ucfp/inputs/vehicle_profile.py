"""Vehicles: the household's current vehicles as one Profile section -- owned and leased together.

A vehicle is owned or leased, the user's single choice per car, but it is one item in one list -- the way
someone thinks about the cars in their driveway. Under the covers the two are stored differently: an
**owned** vehicle is flat profile facts that belong together (a `DEPRECIATING` `AssetProfile` and any
`AUTO` `Debt` secured against it, its balance entered here and shown read-only in Debts); a **leased**
vehicle is a thin `LeasedVehicle` fact (a lease confers no ownership -- its terms and end-of-term plan are
the vehicle plan's). Both share one handle space (`vehicle-N`), so a vehicle keeps its identity when its
owned/leased choice is flipped: the form moves it between the asset store and the lease-fact store, and
its now-mismatched vehicle-plan disposition is dropped (the owned and leased kinds differ). This module
owns adding, editing, and removing a vehicle of either kind, and the combined list the section renders.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField, StyledFormMixin

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.compatibility import plans_without_vehicles
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, LeasedVehicle
from ucfp.inputs.properties import delete_property

_VEHICLE_PREFIX = 'vehicle-'

OWNED  = 'owned'
LEASED = 'leased'
_OWNERSHIP_CHOICES = ( ( OWNED, 'Owned' ), ( LEASED, 'Leased' ) )


def _loan_handle( vehicle_handle : str ) -> str:
    """The stable handle of the auto loan secured against an owned vehicle -- derived from the vehicle's
    own handle (mirroring a mortgage's `{handle}-mortgage`), so the pair travels together and a sale, a
    delete, or a switch to leased can find it."""
    return f'{vehicle_handle}-loan'


def _minted_current_vehicle_handle( profile ) -> str:
    """A fresh `vehicle-N` handle, the lowest free among *every* current vehicle -- owned (a DEPRECIATING
    asset) or leased (a fact) -- so the two share one identity space and a vehicle keeps its handle when
    its owned/leased choice is flipped."""
    taken = { asset.handle for asset in profile.assets } | { v.handle for v in profile.leased_vehicles }
    index = 1
    while f'{_VEHICLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_VEHICLE_PREFIX}{index}'


def current_vehicles_context( profile ) -> list:
    """The household's current vehicles for the list -- owned holdings then leased facts, each with its
    handle, name, ownership label, and (owned only) value."""
    owned = [ { 'handle': asset.handle, 'name': asset.name, 'ownership': 'Owned',
                'value': asset.opening_value }
              for asset in profile.assets if asset.asset_class is AssetClass.DEPRECIATING ]
    leased = [ { 'handle': vehicle.handle, 'name': vehicle.name, 'ownership': 'Leased', 'value': None }
               for vehicle in profile.leased_vehicles ]
    return owned + leased


def delete_current_vehicle( profile, plans, handle : str ):
    """Remove a current vehicle -- an owned holding (and its secured loan, via `delete_property`) or a
    leased fact -- and drop any vehicle-plan disposition keyed to it (owned or leased)."""
    if any( asset.handle == handle for asset in profile.assets ):
        profile, plans = delete_property( profile, plans, handle )
    else:
        profile = replace(
            profile, leased_vehicles = [ v for v in profile.leased_vehicles if v.handle != handle ] )
    return profile, plans_without_vehicles( plans, { handle } )


class CurrentVehicleForm( StyledFormMixin, forms.Form ):
    """One current vehicle, owned or leased -- the user's single choice, driving which fields apply. The
    ownership radio is a switch (inputs.js): Owned reveals the current value and any auto-loan balance
    (written as a `DEPRECIATING` holding + an `AUTO` `Debt`); Leased reveals nothing more (written as a
    `LeasedVehicle` fact). Non-blocking and handle-minted: it materializes only once its needed fields are
    set (a name, plus a value when owned), leaving other vehicles intact. Flipping ownership on an
    existing vehicle moves it between the two stores under the same handle and drops its now-mismatched
    disposition."""

    name      = forms.CharField( label = 'Name', max_length = 100, required = False )
    ownership = forms.ChoiceField(
        label = 'This vehicle is', required = False, choices = _OWNERSHIP_CHOICES, initial = OWNED,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    value        = MoneyField( label = 'Current value', min_value = 0, required = False )
    loan_balance = MoneyField(
        label = 'Auto-loan balance owed (optional)', min_value = 0, required = False )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        super().__init__( data, initial = self._initial( profile, handle ) if handle else None )
        self._profile = profile
        self._plans   = plans
        self._handle  = handle

    @classmethod
    def _initial( cls, profile, handle : str ) -> dict:
        asset = next( ( a for a in profile.assets if a.handle == handle ), None )
        if asset is not None:
            initial = { 'ownership': OWNED, 'name': asset.name, 'value': asset.opening_value }
            loan    = next( ( d for d in profile.debts if d.handle == _loan_handle( handle ) ), None )
            if loan is not None:
                initial[ 'loan_balance' ] = loan.balance
            return initial
        leased = next( ( v for v in profile.leased_vehicles if v.handle == handle ), None )
        if leased is not None:
            return { 'ownership': LEASED, 'name': leased.name }
        return dict()

    @property
    def owned_case( self ) -> str:
        """The ownership value whose extra fields (value, loan) show -- its switch-case value."""
        return OWNED

    def _ownership( self ) -> str:
        return self.cleaned_data.get( 'ownership' ) or OWNED

    def _complete( self ) -> bool:
        """The fields the vehicle needs to materialize are present -- a name always, and a value when
        owned (a leased vehicle needs only its name here). No hard validation: a partial vehicle is simply
        not written rather than fighting a background save."""
        cleaned = self.cleaned_data
        if not cleaned.get( 'name' ):
            return False
        if self._ownership() == OWNED:
            return cleaned.get( 'value' ) is not None
        return True

    def apply( self, profile, plans ):
        # Non-blocking and non-destructive: a partial edit writes nothing and leaves other vehicles
        # intact. A complete form writes the vehicle in the store its ownership chooses, removing it from
        # the other; if that flips its type, its now-mismatched disposition is dropped.
        if not self._complete():
            return profile, plans
        handle     = self._handle or _minted_current_vehicle_handle( profile )
        was_owned  = any( asset.handle == handle for asset in profile.assets )
        was_leased = any( vehicle.handle == handle for vehicle in profile.leased_vehicles )
        if self._ownership() == LEASED:
            profile = self._as_leased( profile, handle )
            if was_owned:                                    # type flipped -> its owned disposition is stale
                plans = plans_without_vehicles( plans, { handle } )
        else:
            profile = self._as_owned( profile, handle )
            if was_leased:                                   # type flipped -> its leased disposition is stale
                plans = plans_without_vehicles( plans, { handle } )
        return profile, plans

    def _as_owned( self, profile, handle : str ):
        loan     = _loan_handle( handle )
        existing = next( ( d for d in profile.debts if d.handle == loan ), None )
        return replace(
            profile,
            assets          = ( [ a for a in profile.assets if a.handle != handle ]
                                + [ self._asset( handle ) ] ),
            debts           = ( [ d for d in profile.debts if d.handle != loan ]
                                + self._loan( handle, existing ) ),
            leased_vehicles = [ v for v in profile.leased_vehicles if v.handle != handle ] )

    def _as_leased( self, profile, handle : str ):
        loan = _loan_handle( handle )
        return replace(
            profile,
            leased_vehicles = ( [ v for v in profile.leased_vehicles if v.handle != handle ]
                                + [ LeasedVehicle( handle = handle, name = self.cleaned_data[ 'name' ] ) ] ),
            assets          = [ a for a in profile.assets if a.handle != handle ],
            debts           = [ d for d in profile.debts if d.handle != loan ] )

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.DEPRECIATING,
            opening_value = cleaned[ 'value' ] )

    def _loan( self, vehicle_handle : str, existing ) -> list:
        # The vehicle-secured auto loan, present only when a balance is entered. The vehicle is a
        # balance-only surface onto the one debt; the name and kind the Debts section may have set are
        # preserved.
        balance = self.cleaned_data.get( 'loan_balance' )
        if balance is None:
            return []
        return [ Debt(
            handle = _loan_handle( vehicle_handle ),
            name = existing.name if existing is not None else f"{self.cleaned_data[ 'name' ]} Loan",
            kind = existing.kind if existing is not None else DebtKind.AUTO,
            balance = balance, secured_asset = vehicle_handle ) ]
