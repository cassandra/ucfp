"""Vehicles: an owned vehicle as a Profile unit -- the holding and any auto loan still owed.

Vehicles are their own Profile section, mirroring Real Estate. An owned vehicle is flat profile facts
that belong together -- a `DEPRECIATING` `AssetProfile` and any `AUTO` `Debt` secured against it (its
balance entered here and shown read-only in Debts) -- tied by a shared vehicle handle. This parallels a
mortgaged property's holding + mortgage: `VehicleHoldingForm` mirrors `properties._PropertyForm`
(loan where it says mortgage) and reuses its pane, list/edit views, and delete, so the app keeps seeing
flat asset/debt lists while the user works with a whole vehicle. The holding is `DEPRECIATING`, so the
materialization already built for vehicles (sale, running costs, the plan link) reaches it unchanged.

A leased vehicle -- a fact with no holding -- is not modeled here yet; it arrives with the vehicle
plan's dispositions, alongside the lease terms it is bound to. The near-duplication of the property
form's `apply`/`_initial` skeleton is deliberate for now: unifying the two behind a shared holding base
is a follow-up refactor, kept out of the section's first cut.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField, StyledFormMixin

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.compatibility import plans_without_vehicles
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt
from ucfp.inputs.properties import PropertyPane, _minted_handle, delete_property

_VEHICLE_PREFIX = 'vehicle-'


def _loan_handle( vehicle_handle : str ) -> str:
    """The stable handle of the auto loan secured against a vehicle -- derived from the vehicle's own
    handle (mirroring a mortgage's `{handle}-mortgage`), so the pair travels together and a sale or a
    delete can find it."""
    return f'{vehicle_handle}-loan'


class VehicleHoldingForm( StyledFormMixin, forms.Form ):
    """One owned vehicle as a unit: the holding (name, current value) and any auto-loan balance still
    owed. It writes a `DEPRECIATING` `AssetProfile` -- no cost basis, since a vehicle's sale is tax-free
    -- and, when a balance is entered, an `AUTO` `Debt` secured against it (the same debt the Debts
    section shows read-only; its repayment is set in the Debt plan). Non-blocking and handle-minted like
    a property: it materializes only once name and value are set, and leaves other vehicles intact. This
    mirrors `properties._PropertyForm` with a loan in place of a mortgage."""

    _PREFIX       = _VEHICLE_PREFIX
    _ASSET_FIELDS = ( 'name', 'value' )
    field_order   = [ 'name', 'value', 'loan_balance' ]

    name         = forms.CharField( label = 'Name', max_length = 100, required = False )
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
        if asset is None:
            return dict()
        initial = { 'name': asset.name, 'value': asset.opening_value }
        loan    = next( ( d for d in profile.debts if d.handle == _loan_handle( handle ) ), None )
        if loan is not None:
            initial[ 'loan_balance' ] = loan.balance
        return initial

    @property
    def primary_fields( self ):
        """The vehicle fields, in `field_order`."""
        return [ self[ name ] for name in self.fields ]

    def _complete( self ) -> bool:
        """Name and value are both present -- the condition for materializing the vehicle. Like a
        property, there is no hard validation; a half-entered vehicle is simply not written."""
        cleaned = self.cleaned_data
        return all( cleaned.get( field ) not in ( None, '' ) for field in self._ASSET_FIELDS )

    def apply( self, profile, plans ):
        # Non-blocking and non-destructive, exactly as a property's: a partial edit writes nothing and
        # leaves any existing vehicle (and its loan) untouched; only the explicit delete removes one. A
        # complete form writes its holding and, if a balance is entered, its secured auto loan.
        if not self._complete():
            return profile, plans
        handle   = self._handle or _minted_handle( profile, self._PREFIX )
        loan     = _loan_handle( handle )
        existing = next( ( d for d in profile.debts if d.handle == loan ), None )
        assets   = [ a for a in profile.assets if a.handle != handle ] + [ self._asset( handle ) ]
        debts    = [ d for d in profile.debts if d.handle != loan ] + self._loan( handle, existing )
        return replace( profile, assets = assets, debts = debts ), plans

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


VEHICLE_PANE = PropertyPane(
    form = VehicleHoldingForm, asset_class = AssetClass.DEPRECIATING, heading = 'Vehicles',
    list_id = 'vehicles-holding-list', form_id = 'vehicles-holding-form',
    add_url = 'vehicle_holding_add', edit_url = 'vehicle_holding_edit',
    delete_url = 'vehicle_holding_delete',
    add_text = 'Add a vehicle', empty_text = 'No vehicles.' )

# The vehicle panes in display order, iterated by the Vehicles section and mapped to their
# add/edit/delete views. One kind today; a tuple to match the property panes' shape.
VEHICLE_PANES = ( VEHICLE_PANE, )


def delete_vehicle_holding( profile, plans, vehicle_handle : str ):
    """Remove an owned vehicle as a unit -- its holding and any secured auto loan (`delete_property`) --
    and drop any vehicle-plan disposition keyed to it, so a deleted vehicle leaves nothing dangling."""
    profile, plans = delete_property( profile, plans, vehicle_handle )
    return profile, plans_without_vehicles( plans, { vehicle_handle } )
