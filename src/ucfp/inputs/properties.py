"""§3 mortgaged properties: a rental or a second home, each handled as a unit.

A mortgaged property is flat profile facts that belong together -- the holding (an `AssetProfile`) and
any mortgage (a `Debt` secured against it, its balance entered here and shown read-only in Debts) --
tied by a shared property handle. This module owns creating, editing, and removing such a property as
one, so the rest of the app keeps seeing flat lists while the user works with a whole property. A
rental additionally carries depreciation attributes (a `PropertyProfile`) and, in Income, a gross
rent; a second home is personal-use with neither. Operating expenses attach in Home Expenses by the
same handle.
"""
from dataclasses import replace
from itertools import zip_longest

from django import forms
from django.urls import reverse

from common.forms import CHOOSE_PLACEHOLDER, MoneyField, StyledFormMixin

from ucfp.accounts.enums import AssetClass, RealPropertyType
from ucfp.environment.constants import AppConst
from ucfp.inputs.loan_fieldset import LoanTermsFieldsMixin, loan_terms_initial
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, PropertyProfile
from ucfp.inputs.widgets import IsoDateInput


def _minted_handle( profile, prefix : str ) -> str:
    """A fresh `{prefix}N` handle, the lowest index free among the profile's holdings."""
    taken = { asset.handle for asset in profile.assets }
    index = 1
    while f'{prefix}{index}' in taken:
        index += 1
    return f'{prefix}{index}'


def _mortgage_handle( property_handle : str ) -> str:
    """The stable handle of the mortgage debt secured against a property -- derived from the
    property's own handle, so the pair travels together and a sale (`delete_property`) can find it."""
    return f'{property_handle}-mortgage'


_PROPERTY_BADGE = {
    AssetClass.REAL_ESTATE_RENTAL      : 'Rental',
    AssetClass.REAL_ESTATE_SECOND_HOME : 'Second home',
}


def properties_context( profile ) -> list:
    """The household's other-property holdings -- rentals and second homes together -- for the list: each
    one's handle, name, value, a type badge, and the Edit/Remove urls its item card posts to. A rental's
    rent is set in the Income section, not here."""
    rows = []
    for asset in profile.assets:
        badge = _PROPERTY_BADGE.get( asset.asset_class )
        if badge is None:
            continue
        rows.append( { 'handle'     : asset.handle,
                       'name'       : asset.name,
                       'value'      : asset.opening_value,
                       'badge'      : badge,
                       'edit_url'   : reverse( 'property_edit', kwargs = { 'handle' : asset.handle } ),
                       'delete_url' : reverse( 'property_delete', kwargs = { 'handle' : asset.handle } ) } )
    return rows


def property_heading( profile, handle : str ):
    """The {handle, name, badge} of a saved property for the editor card header, or None when the handle
    names no saved property yet (a just-added one being filled in)."""
    asset = next( ( a for a in profile.assets if a.handle == handle
                    and a.asset_class in _PROPERTY_BADGE ), None )
    if asset is None:
        return None
    return { 'handle' : handle, 'name' : asset.name, 'badge' : _PROPERTY_BADGE[ asset.asset_class ] }


def delete_property( profile, plans, property_handle : str ):
    """Remove a property as a unit: its holding, any gross income, and any debts secured against it. Plans
    are left untouched -- a plan (a secured debt's repayment/payoff, an override) left keyed to what was
    removed is reconciled on demand at the run surface, not eagerly here."""
    secured = { debt.handle for debt in profile.debts
                if debt.secured_asset == property_handle }
    profile = replace(
        profile,
        assets       = [ a for a in profile.assets if a.handle != property_handle ],
        income_flows = [ flow for flow in profile.income_flows
                         if flow.property_handle != property_handle ],
        debts        = [ debt for debt in profile.debts if debt.handle not in secured ] )
    return profile, plans


_PROPERTY_PREFIX = 'property-'

# The three property types the unified editor offers, each encoding an asset class (and, for a rental, its
# depreciation type). The two rental types share the rental-only fields; a second home has none.
_RENTAL_RESIDENTIAL = 'RENTAL_RESIDENTIAL'
_RENTAL_COMMERCIAL  = 'RENTAL_COMMERCIAL'
_SECOND_HOME        = 'SECOND_HOME'
_RENTAL_TYPES       = ( _RENTAL_RESIDENTIAL, _RENTAL_COMMERCIAL )
_TYPE_TO_PROPERTY = { _RENTAL_RESIDENTIAL : RealPropertyType.RESIDENTIAL,
                      _RENTAL_COMMERCIAL  : RealPropertyType.COMMERCIAL }
_PROPERTY_TO_TYPE = { real_type : type_value for type_value, real_type in _TYPE_TO_PROPERTY.items() }


class PropertyForm( LoanTermsFieldsMixin, StyledFormMixin, forms.Form ):
    """One other-property holding -- a rental or a second home -- as a unit. The `property_type` select is a
    switch (inputs.js): the two Rental types reveal the rental-only fields (building basis, purchase date)
    and materialize a `REAL_ESTATE_RENTAL` holding with a depreciation `PropertyProfile`; Second Home hides
    them and materializes a `REAL_ESTATE_SECOND_HOME`. Either type may carry a mortgage (the same `Debt` the
    Debts section shows read-only), behind a disclosure. Handle-minted (`property-N`) and non-blocking: it
    materializes only once its needed fields are set, leaving other properties intact. Flipping an existing
    property to Second Home drops its rental rent (set in Income) -- second homes have none."""

    _PREFIX = _PROPERTY_PREFIX
    LOAN_ID = 'property-mortgage'
    _TYPE_CHOICES = ( ( _RENTAL_RESIDENTIAL, 'Rental — Residential' ),
                      ( _RENTAL_COMMERCIAL , 'Rental — Commercial' ),
                      ( _SECOND_HOME       , 'Second Home' ) )
    _COMMON_FIELDS = ( 'name', 'value', 'purchase_price' )      # every property needs these
    _RENTAL_FIELDS = ( 'building_basis', 'acquisition_date' )   # a rental additionally needs these

    property_type    = forms.ChoiceField(
        label = 'Type', required = False, choices = _TYPE_CHOICES, initial = _RENTAL_RESIDENTIAL,
        widget = forms.Select( attrs = { 'class' : f'custom-select {AppConst.SWITCH_CONTROL_CLASS}' } ) )
    name             = forms.CharField( label = 'Name', max_length = 100, required = False )
    value            = MoneyField( label = 'Current value', min_value = 0, required = False )
    purchase_price   = MoneyField( label = 'Purchase price', min_value = 0, required = False )
    building_basis   = MoneyField(
        label = 'Building value at purchase, excludes land', min_value = 0, required = False )
    acquisition_date = forms.DateField(
        label = 'Purchase date', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
    mortgage_balance = MoneyField(
        label = 'Mortgage balance owed', min_value = 0, required = False,
        css_class = AppConst.LOAN_BALANCE_CLASS )

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
        initial = { 'name': asset.name, 'value': asset.opening_value, 'purchase_price': asset.cost_basis }
        if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL and asset.property is not None:
            initial[ 'property_type' ]    = _PROPERTY_TO_TYPE[ asset.property.property_type ]
            initial[ 'building_basis' ]   = asset.property.depreciable_basis
            initial[ 'acquisition_date' ] = asset.property.acquisition_date
        else:
            initial[ 'property_type' ] = _SECOND_HOME
        mortgage = next( ( d for d in profile.debts if d.handle == _mortgage_handle( handle ) ), None )
        if mortgage is not None:
            initial[ 'mortgage_balance' ] = mortgage.balance
            initial.update( loan_terms_initial( mortgage.terms ) )
        return initial

    @property
    def rental_cases( self ) -> str:
        """The type values whose editor reveals the rental-only fields -- the switch-case that block is
        marked with (both rental types, so the block shows for either)."""
        return ' '.join( _RENTAL_TYPES )

    def _type( self ) -> str:
        return self.cleaned_data.get( 'property_type' ) or _RENTAL_RESIDENTIAL

    def _is_rental( self ) -> bool:
        return self._type() in _RENTAL_TYPES

    def _complete( self ) -> bool:
        """The fields the holding needs to materialize -- the common fields always, plus the rental-only
        fields when the chosen type is a rental. Non-blocking: a partial property is simply not written."""
        cleaned = self.cleaned_data
        needed  = self._COMMON_FIELDS + ( self._RENTAL_FIELDS if self._is_rental() else () )
        return all( cleaned.get( field ) not in ( None, '' ) for field in needed )

    def apply( self, profile, plans ):
        # Non-blocking and non-destructive: a partial edit writes nothing and leaves other properties
        # intact. A complete form writes the holding in the class its type chooses (a rental carries a
        # depreciation profile; a second home does not) and, if a balance is entered, its secured mortgage.
        # Flipping to Second Home drops any rental rent keyed to this property (second homes have none); a
        # rental's rent is set in Income, not here.
        if not self._complete():
            return profile, plans
        handle   = self._handle or _minted_handle( profile, self._PREFIX )
        mortgage = _mortgage_handle( handle )
        existing = next( ( d for d in profile.debts if d.handle == mortgage ), None )
        assets   = [ a for a in profile.assets if a.handle != handle ] + [ self._asset( handle ) ]
        debts    = ( [ d for d in profile.debts if d.handle != mortgage ]
                     + self._mortgage( handle, existing ) )
        income   = ( profile.income_flows if self._is_rental()
                     else [ f for f in profile.income_flows if f.property_handle != handle ] )
        return replace( profile, assets = assets, debts = debts, income_flows = income ), plans

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        if self._is_rental():
            return AssetProfile(
                handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.REAL_ESTATE_RENTAL,
                opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ],
                property = PropertyProfile(
                    acquisition_date = cleaned[ 'acquisition_date' ],
                    depreciable_basis = cleaned[ 'building_basis' ],
                    property_type = _TYPE_TO_PROPERTY[ self._type() ] ) )
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
            opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ] )

    def _mortgage( self, property_handle : str, existing ) -> list:
        # The property-secured mortgage debt, present only when a balance is entered. The property is a
        # balance-only convenience surface onto the one debt; the name and kind the Debts section may have
        # set are preserved.
        balance = self.cleaned_data.get( 'mortgage_balance' )
        if balance is None:
            return []
        return [ Debt(
            handle = _mortgage_handle( property_handle ),
            name = existing.name if existing is not None else f"{self.cleaned_data[ 'name' ]} Mortgage",
            kind = existing.kind if existing is not None else DebtKind.MORTGAGE,
            balance = balance, secured_asset = property_handle,
            terms = self.loan_terms( balance ) ) ]


_POSSESSION_PREFIX = 'possession-'


def _minted_possession_handle( taken : set ) -> str:
    """The lowest `possession-N` handle free among `taken` -- a stable identity a new possession keeps
    across edits, since Plans reference possessions by handle (mirrors the debts form's scheme). Unlike
    `_minted_handle`, it accumulates across a batch via `taken` (possessions are saved as a list)."""
    index = 1
    while f'{_POSSESSION_PREFIX}{index}' in taken:
        index += 1
    return f'{_POSSESSION_PREFIX}{index}'


class PossessionsForm( forms.Form ):
    """Other Possessions -- a background-saved list of tangible holdings the engine treats by class:
    precious metals and collectibles. (Vehicles were once a type here; they are now their own Profile
    section -- see `vehicle_profile`.) Each row is a named item with a value and a type; a trailing
    blank row adds another, and an existing row's Remove box drops it. Non-blocking: a row materializes
    only once its name, value, and type are all set, so a half-filled row is simply ignored. `apply`
    replaces these holdings, leaving other assets intact. Each row carries the item's stable `handle` in
    a hidden field -- Plans reference possessions by it, so identity must survive edits rather than
    being reindexed.
    """

    _CLASSES = ( AssetClass.PRECIOUS_METALS, AssetClass.COLLECTIBLES )
    _TYPE_CHOICES = (
        ( '', CHOOSE_PLACEHOLDER ),
        ( AssetClass.PRECIOUS_METALS.name, 'Precious metals' ),
        ( AssetClass.COLLECTIBLES.name, 'Collectibles' ),
    )
    _VALID_TYPES = frozenset( { AssetClass.PRECIOUS_METALS.name, AssetClass.COLLECTIBLES.name } )
    # The repeated field names of a possession rowset row -- one source with the template's inputs (see
    # `names`), read as parallel getlists and zipped by position.
    _P_TYPE   = 'possession_type'
    _P_NAME   = 'possession_name'
    _P_VALUE  = 'possession_value'
    _P_HANDLE = 'possession_handle'

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._items       = self._existing( profile ) if profile is not None else []
        self._value_field = MoneyField( required = False, min_value = 0 )   # reused to parse rowset values
        self._row_errors  = dict()                     # rowset index -> value error message (set in clean)

    @classmethod
    def _existing( cls, profile ) -> list:
        return [ asset for asset in profile.assets if asset.asset_class in cls._CLASSES ]

    @property
    def names( self ) -> dict:
        """The rowset field names -- one source shared with the template's inputs and the getlist keys."""
        return { 'type' : self._P_TYPE, 'name' : self._P_NAME,
                 'value' : self._P_VALUE, 'handle' : self._P_HANDLE }

    @property
    def type_choices( self ) -> tuple:
        return self._TYPE_CHOICES

    def _posted( self ):
        """The posted rows as `(type, name, value, handle)` tuples, zipped by position -- one per rendered
        rowset row (the blank <template> prototype is inert, so it never posts)."""
        return zip_longest(
            self.data.getlist( self._P_TYPE ), self.data.getlist( self._P_NAME ),
            self.data.getlist( self._P_VALUE ), self.data.getlist( self._P_HANDLE ), fillvalue = '' )

    @property
    def rows( self ) -> list:
        """The possession rows for the rowset. Bound (a re-render after an edit): the submitted values, so
        typing survives an error re-render, each with any value error. Unbound (first load): the stored
        items."""
        if self.is_bound:
            return [ { 'type' : type_, 'name' : name, 'value' : value, 'handle' : handle,
                       'error' : self._row_errors.get( i ) }
                     for i, ( type_, name, value, handle ) in enumerate( self._posted() ) ]
        return [ { 'type' : item.asset_class.name, 'name' : item.name, 'value' : item.opening_value,
                   'handle' : item.handle, 'error' : None }
                 for item in self._items ]

    def _parse_value( self, raw : str ):
        """A posted value as a non-negative Decimal, or None when blank or invalid -- the declared cells'
        own parse, reused."""
        try:
            return self._value_field.clean( raw )
        except forms.ValidationError:
            return None

    def clean( self ):
        """Surface a negative value as a genuine error (so the pane re-renders it), keyed to its row for
        the template; a blank or otherwise-incomplete row stays non-blocking."""
        cleaned = super().clean()
        for i, ( _type, _name, value, _handle ) in enumerate( self._posted() ):
            if not value:
                continue
            try:
                self._value_field.clean( value )
            except forms.ValidationError as error:
                self._row_errors[ i ] = ' '.join( error.messages )
        if self._row_errors:
            raise forms.ValidationError( 'Check the highlighted values.' )
        return cleaned

    def apply( self, profile, plans ):
        kept = [ asset for asset in profile.assets if asset.asset_class not in self._CLASSES ]
        return replace( profile, assets = kept + self._possessions( kept ) ), plans

    def _possessions( self, kept : list[ AssetProfile ] ) -> list:
        # Existing rows keep the handle their hidden field carries; new rows mint one free among every
        # asset in play -- the possessions being rebuilt AND the retained assets. The latter matters
        # because a transition-era holding (a pre-split vehicle) can still occupy a `possession-N`; minting
        # only against the possessions being rebuilt would re-mint onto it and collide at persistence.
        taken = { asset.handle for asset in ( self._items + kept ) if asset.handle is not None }
        taken |= { handle for handle in self.data.getlist( self._P_HANDLE ) if handle }
        possessions = []
        for type_raw, name, value_raw, handle_raw in self._posted():
            value = self._parse_value( value_raw )
            if not name or value is None or type_raw not in self._VALID_TYPES:
                continue                                     # incomplete/invalid row -- not materialized
            handle = handle_raw or _minted_possession_handle( taken )
            taken.add( handle )
            possessions.append( AssetProfile(
                handle = handle, name = name, asset_class = AssetClass[ type_raw ], opening_value = value ) )
        return possessions
