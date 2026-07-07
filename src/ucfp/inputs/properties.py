"""§3 rentals: a rental property handled as a unit.

A rental is flat profile facts that belong together -- the holding (`AssetProfile`,
`REAL_ESTATE_RENTAL`) and its gross rent (an `IncomeFlow` carrying the property handle, set in the
Income section) -- tied by a shared property handle. This module owns creating, editing, and removing
the property as one, so the rest of the app keeps seeing flat lists while the user works with a whole
property. Any mortgage is a `Debt` secured against the property (its balance entered here, shown
read-only in Debts); operating expenses attach in spending (§6), and the rent in income (§5), by the
same handle.
"""
from dataclasses import replace

from django import forms

from ucfp.accounts.enums import AssetClass, RealPropertyType
from ucfp.environment.constants import AppConst
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, PropertyProfile
from ucfp.inputs.widgets import IsoDateInput


_RENTAL_HANDLE_PREFIX = 'rental-'


def _minted_rental_handle( profile ) -> str:
    """A fresh `rental-N` handle, the lowest index free among the profile's holdings."""
    taken = { asset.handle for asset in profile.assets }
    index = 1
    while f'{_RENTAL_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_RENTAL_HANDLE_PREFIX}{index}'


def _rental_mortgage_handle( property_handle : str ) -> str:
    """The stable handle of the mortgage debt secured against a rental -- derived from the property's
    own handle, so the pair travels together and a sale (`delete_rental`) can find it."""
    return f'{property_handle}-mortgage'


def rentals_context( profile ) -> list:
    """The rentals for the list template: each rental's handle, name, and value. The rent is set in
    the Income section, not here."""
    return [ { 'handle': asset.handle, 'name': asset.name, 'value': asset.opening_value }
             for asset in profile.assets
             if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]


def delete_rental( profile, plans, property_handle : str ):
    """Remove a rental as a unit: its holding, gross income, any debts secured against it, those
    debts' repayment/prepayment plans, and any operating expenses attached to it."""
    secured = { debt.handle for debt in profile.debts
                if debt.secured_asset == property_handle }
    profile = replace(
        profile,
        assets       = [ a for a in profile.assets if a.handle != property_handle ],
        income_flows = [ flow for flow in profile.income_flows
                         if flow.property_handle != property_handle ],
        debts        = [ debt for debt in profile.debts if debt.handle not in secured ] )
    plans = replace(
        plans,
        loan_repayments = [ r for r in plans.loan_repayments if r.debt_handle not in secured ],
        prepayments     = [ p for p in plans.prepayments if p.loan_handle not in secured ],
        expenses        = [ e for e in plans.expenses if e.property_handle != property_handle ] )
    return profile, plans


class RentalForm( forms.Form ):
    """One rental property as a unit: the holding (value, basis, acquisition, type) and any mortgage
    balance still owed. It is household-owned -- like the residence, and because the engine taxes
    rentals as one aggregate passive activity, no per-owner rule applies -- so there is no owner
    field. `apply` writes the asset and its mortgage debt under one property handle, leaving other
    properties intact. The mortgage is the same `Debt` the Debts section shows read-only; the gross
    rent is set in Income."""

    # The asset fields are all optional individually: the form background-saves and the rental
    # materializes only once all of these are set (see `_rental_complete`), so a just-opened blank
    # that is abandoned never appears. The mortgage balance is separate -- it rides along on a
    # materialized rental but is not required to complete one.
    _ASSET_FIELDS = ( 'name', 'value', 'purchase_price', 'acquisition_date',
                      'building_basis', 'property_type' )

    name             = forms.CharField( label = 'Name', max_length = 100, required = False )
    value            = forms.DecimalField( label = 'Current value', min_value = 0, required = False )
    building_basis   = forms.DecimalField(
        label = 'Building value, excludes land (for depreciation)', min_value = 0, required = False )
    purchase_price   = forms.DecimalField( label = 'Purchase price', min_value = 0, required = False )
    mortgage_balance = forms.DecimalField(
        label = 'Mortgage balance owed (optional)', min_value = 0, required = False )
    acquisition_date = forms.DateField(
        label = 'Purchase date', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
    property_type    = forms.ChoiceField(
        label = 'Type', required = False,
        choices = [ ( '', 'Type...' ) ] + [ ( k.name, k.label ) for k in RealPropertyType ] )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        super().__init__(
            data, initial = self._initial( profile, plans, handle ) if handle else None )
        self._profile  = profile
        self._plans = plans
        self._handle   = handle

    @classmethod
    def _initial( cls, profile, plans, handle : str ) -> dict:
        asset = next( ( a for a in profile.assets if a.handle == handle ), None )
        if asset is None:
            return dict()
        initial = { 'name': asset.name, 'value': asset.opening_value,
                    'purchase_price': asset.cost_basis }
        if asset.property is not None:
            initial[ 'acquisition_date' ] = asset.property.acquisition_date
            initial[ 'building_basis' ]   = asset.property.depreciable_basis
            initial[ 'property_type' ]    = asset.property.property_type.name
        mortgage = next( ( d for d in profile.debts
                           if d.handle == _rental_mortgage_handle( handle ) ), None )
        if mortgage is not None:
            initial[ 'mortgage_balance' ] = mortgage.balance
        return initial

    @property
    def primary_fields( self ):
        """The holding fields, in declaration order."""
        return [ self[ name ] for name in self.fields ]

    def _rental_complete( self ) -> bool:
        """All fields the rental asset needs are present -- the condition for materializing it. There
        is no hard validation, so a partially-entered rental is simply not written rather than
        fighting a background save."""
        cleaned = self.cleaned_data
        return all( cleaned.get( field ) not in ( None, '' ) for field in self._ASSET_FIELDS )

    def apply( self, profile, plans ):
        handle   = self._handle or _minted_rental_handle( profile )
        mortgage = _rental_mortgage_handle( handle )
        existing = self._find( profile.debts, mortgage )
        # Non-blocking: an incomplete rental (and so its mortgage) materializes nothing, and editing
        # an existing one to incomplete removes both; a complete rental writes its asset and, if a
        # balance is entered, its mortgage debt.
        complete = self._rental_complete()
        assets   = self._without( profile.assets, 'handle', handle ) + (
            [ self._asset( handle ) ] if complete else [] )
        debts    = self._without( profile.debts, 'handle', mortgage ) + (
            self._mortgage( handle, existing ) if complete else [] )
        return replace( profile, assets = assets, debts = debts ), plans

    @staticmethod
    def _without( items : list, attribute : str, value ) -> list:
        return [ item for item in items if getattr( item, attribute ) != value ]

    @staticmethod
    def _find( items : list, handle : str ):
        return next( ( item for item in items if item.handle == handle ), None )

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ],
            property = PropertyProfile(
                acquisition_date = cleaned[ 'acquisition_date' ],
                depreciable_basis = cleaned[ 'building_basis' ],
                property_type = RealPropertyType[ cleaned[ 'property_type' ] ] ) )

    def _mortgage( self, property_handle : str, existing ) -> list:
        # The rental-secured mortgage debt, present only when a balance is entered. The rental is a
        # balance-only convenience surface onto the one debt; the name and kind the Debts section may
        # have set are preserved. Its interest is treated as a rental expense at materialization
        # (keyed on the secured asset being a rental).
        balance = self.cleaned_data.get( 'mortgage_balance' )
        if balance is None:
            return []
        return [ Debt(
            handle = _rental_mortgage_handle( property_handle ),
            name = existing.name if existing is not None else f"{self.cleaned_data[ 'name' ]} Mortgage",
            kind = existing.kind if existing is not None else DebtKind.MORTGAGE,
            balance = balance, secured_asset = property_handle ) ]


class PossessionsForm( forms.Form ):
    """Other Possessions -- a background-saved list of tangible holdings the engine treats by class:
    precious metals, collectibles, and depreciating assets (vehicles, boats). Each row is a named item
    with a value and a type; a trailing blank row adds another, and an existing row's Remove box drops
    it. Non-blocking: a row materializes only once its name, value, and type are all set, so a
    half-filled row is simply ignored. `apply` replaces these holdings, leaving other assets intact.
    """

    _CLASSES = ( AssetClass.PRECIOUS_METALS, AssetClass.COLLECTIBLES, AssetClass.DEPRECIATING )
    _TYPE_CHOICES = (
        ( '', 'Type...' ),
        ( AssetClass.PRECIOUS_METALS.name, 'Precious metals' ),
        ( AssetClass.COLLECTIBLES.name, 'Collectibles' ),
        ( AssetClass.DEPRECIATING.name, 'Vehicle or boat' ),
    )
    _HANDLE_PREFIX = 'possession-'

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._items = self._existing( profile ) if profile is not None else []
        for index in range( len( self._items ) + 1 ):   # existing rows, then one blank to add
            self._build_row( index )

    @classmethod
    def _existing( cls, profile ) -> list:
        return [ asset for asset in profile.assets if asset.asset_class in cls._CLASSES ]

    def _build_row( self, index : int ):
        item = self._items[ index ] if index < len( self._items ) else None
        self.fields[ f'name_{index}' ]  = forms.CharField(
            required = False, max_length = 100, initial = item.name if item else None )
        self.fields[ f'value_{index}' ] = forms.DecimalField(
            required = False, min_value = 0, initial = item.opening_value if item else None )
        self.fields[ f'type_{index}' ]  = forms.ChoiceField(
            required = False, choices = self._TYPE_CHOICES,
            initial = item.asset_class.name if item else None )
        if item is not None:
            self.fields[ f'remove_{index}' ] = forms.BooleanField( required = False )

    @property
    def rows( self ) -> list:
        rows = []
        for index in range( len( self._items ) + 1 ):
            remove = f'remove_{index}'
            rows.append( {
                'name'   : self[ f'name_{index}' ],
                'type'   : self[ f'type_{index}' ],
                'value'  : self[ f'value_{index}' ],
                'remove' : self[ remove ] if remove in self.fields else None,
            } )
        return rows

    def apply( self, profile, plans ):
        kept = [ asset for asset in profile.assets if asset.asset_class not in self._CLASSES ]
        return replace( profile, assets = kept + self._possessions() ), plans

    def _possessions( self ) -> list:
        possessions = []
        for index in range( len( self._items ) + 1 ):
            if self.cleaned_data.get( f'remove_{index}' ):
                continue
            name  = self.cleaned_data.get( f'name_{index}' )
            value = self.cleaned_data.get( f'value_{index}' )
            kind  = self.cleaned_data.get( f'type_{index}' )
            if not name or value is None or not kind:
                continue                                     # incomplete row -- not materialized
            possessions.append( AssetProfile(
                handle = f'{self._HANDLE_PREFIX}{len( possessions )}', name = name,
                asset_class = AssetClass[ kind ], opening_value = value ) )
        return possessions
