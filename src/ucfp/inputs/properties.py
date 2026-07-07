"""§3 mortgaged properties: a rental or a second home, each handled as a unit.

A mortgaged property is flat profile facts that belong together -- the holding (an `AssetProfile`) and
any mortgage (a `Debt` secured against it, its balance entered here and shown read-only in Debts) --
tied by a shared property handle. This module owns creating, editing, and removing such a property as
one, so the rest of the app keeps seeing flat lists while the user works with a whole property. A
rental additionally carries depreciation attributes (a `PropertyProfile`) and, in Income, a gross
rent; a second home is personal-use with neither. Operating expenses attach in spending (§6) by the
same handle.
"""
from dataclasses import dataclass, replace

from django import forms

from ucfp.accounts.enums import AssetClass, RealPropertyType
from ucfp.environment.constants import AppConst
from ucfp.inputs.compatibility import plans_without_debts
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


def properties_context( profile, asset_class : AssetClass ) -> list:
    """The holdings of one real-estate class for a list template: each one's handle, name, and value.
    A rental's rent is set in the Income section, not here."""
    return [ { 'handle': asset.handle, 'name': asset.name, 'value': asset.opening_value }
             for asset in profile.assets
             if asset.asset_class is asset_class ]


def delete_property( profile, plans, property_handle : str ):
    """Remove a property as a unit: its holding, any gross income, any debts secured against it and
    their full plan reap (repayment, extra principal, payoff), and any operating expenses attached."""
    secured = { debt.handle for debt in profile.debts
                if debt.secured_asset == property_handle }
    profile = replace(
        profile,
        assets       = [ a for a in profile.assets if a.handle != property_handle ],
        income_flows = [ flow for flow in profile.income_flows
                         if flow.property_handle != property_handle ],
        debts        = [ debt for debt in profile.debts if debt.handle not in secured ] )
    plans = plans_without_debts( plans, secured )
    plans = replace(
        plans, expenses = [ e for e in plans.expenses if e.property_handle != property_handle ] )
    return profile, plans


class _PropertyForm( forms.Form ):
    """The shared skeleton for a mortgaged, handle-minted property (a rental, a second home): the
    mortgage-balance field and the `apply` that writes the holding and its secured mortgage debt under
    one property handle, leaving other properties intact. The mortgage is the same `Debt` the Debts
    section shows read-only; its interest tax treatment is chosen at materialization from the secured
    asset's class. A concrete property declares its own holding fields plus `_PREFIX` (its handle
    stem), `_ASSET_FIELDS` (which must all be set before it materializes), `field_order` (to place the
    inherited mortgage field among them), and how to build its `AssetProfile` (`_asset`) and edit
    initials (`_asset_initial`)."""

    # The holding fields are all optional individually: the form background-saves and the property
    # materializes only once all of `_ASSET_FIELDS` are set (see `_complete`), so a just-opened blank
    # that is abandoned never appears. The mortgage balance is separate -- it rides along on a
    # materialized property but is not required to complete one.
    _PREFIX       : str   = ''
    _ASSET_FIELDS : tuple = ()

    mortgage_balance = forms.DecimalField(
        label = 'Mortgage balance owed (optional)', min_value = 0, required = False )

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
        initial  = cls._asset_initial( asset )
        mortgage = next( ( d for d in profile.debts if d.handle == _mortgage_handle( handle ) ), None )
        if mortgage is not None:
            initial[ 'mortgage_balance' ] = mortgage.balance
        return initial

    @staticmethod
    def _asset_initial( asset ) -> dict:
        """The edit-form initials from a saved holding (name, value, and any type-specific fields)."""
        raise NotImplementedError

    @property
    def primary_fields( self ):
        """The holding fields, in `field_order`."""
        return [ self[ name ] for name in self.fields ]

    def _complete( self ) -> bool:
        """All fields the holding needs are present -- the condition for materializing it. There is no
        hard validation, so a partially-entered property is simply not written rather than fighting a
        background save."""
        cleaned = self.cleaned_data
        return all( cleaned.get( field ) not in ( None, '' ) for field in self._ASSET_FIELDS )

    def apply( self, profile, plans ):
        handle   = self._handle or _minted_handle( profile, self._PREFIX )
        mortgage = _mortgage_handle( handle )
        existing = next( ( d for d in profile.debts if d.handle == mortgage ), None )
        # Non-blocking: an incomplete property (and so its mortgage) materializes nothing, and editing
        # an existing one to incomplete removes both; a complete one writes its asset and, if a balance
        # is entered, its mortgage debt.
        complete = self._complete()
        assets   = [ a for a in profile.assets if a.handle != handle ] + (
            [ self._asset( handle ) ] if complete else [] )
        debts    = [ d for d in profile.debts if d.handle != mortgage ] + (
            self._mortgage( handle, existing ) if complete else [] )
        return replace( profile, assets = assets, debts = debts ), plans

    def _asset( self, handle : str ) -> AssetProfile:
        raise NotImplementedError

    def _mortgage( self, property_handle : str, existing ) -> list:
        # The property-secured mortgage debt, present only when a balance is entered. The property is a
        # balance-only convenience surface onto the one debt; the name and kind the Debts section may
        # have set are preserved.
        balance = self.cleaned_data.get( 'mortgage_balance' )
        if balance is None:
            return []
        return [ Debt(
            handle = _mortgage_handle( property_handle ),
            name = existing.name if existing is not None else f"{self.cleaned_data[ 'name' ]} Mortgage",
            kind = existing.kind if existing is not None else DebtKind.MORTGAGE,
            balance = balance, secured_asset = property_handle ) ]


class RentalForm( _PropertyForm ):
    """One rental property as a unit: the holding (value, basis, acquisition, type) and any mortgage
    balance still owed. It is household-owned -- like the residence, and because the engine taxes
    rentals as one aggregate passive activity, no per-owner rule applies -- so there is no owner field.
    It sets a `PropertyProfile` for depreciation; the gross rent is set in Income, and its mortgage
    interest nets against rental income at materialization (keyed on the secured asset being a
    rental)."""

    _PREFIX       = 'rental-'
    _ASSET_FIELDS = ( 'name', 'value', 'purchase_price', 'acquisition_date',
                      'building_basis', 'property_type' )
    field_order   = [ 'name', 'value', 'building_basis', 'purchase_price', 'mortgage_balance',
                      'acquisition_date', 'property_type' ]

    name             = forms.CharField( label = 'Name', max_length = 100, required = False )
    value            = forms.DecimalField( label = 'Current value', min_value = 0, required = False )
    building_basis   = forms.DecimalField(
        label = 'Building value, excludes land (for depreciation)', min_value = 0, required = False )
    purchase_price   = forms.DecimalField( label = 'Purchase price', min_value = 0, required = False )
    acquisition_date = forms.DateField(
        label = 'Purchase date', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
    property_type    = forms.ChoiceField(
        label = 'Type', required = False,
        choices = [ ( '', 'Type...' ) ] + [ ( k.name, k.label ) for k in RealPropertyType ] )

    @staticmethod
    def _asset_initial( asset ) -> dict:
        initial = { 'name': asset.name, 'value': asset.opening_value,
                    'purchase_price': asset.cost_basis }
        if asset.property is not None:
            initial[ 'acquisition_date' ] = asset.property.acquisition_date
            initial[ 'building_basis' ]   = asset.property.depreciable_basis
            initial[ 'property_type' ]    = asset.property.property_type.name
        return initial

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ],
            property = PropertyProfile(
                acquisition_date = cleaned[ 'acquisition_date' ],
                depreciable_basis = cleaned[ 'building_basis' ],
                property_type = RealPropertyType[ cleaned[ 'property_type' ] ] ) )


class SecondHomeForm( _PropertyForm ):
    """One second (vacation) home as a unit: the holding (value, purchase price) and any mortgage
    balance still owed. It is personal-use -- it appreciates and carries a real basis but has no
    depreciation, no rental income, and no §121 exclusion (all consequences of its
    `REAL_ESTATE_SECOND_HOME` class) -- so it carries no `PropertyProfile`, and its mortgage interest
    is an itemizable deduction like the residence's rather than a rental expense."""

    _PREFIX       = 'second-home-'
    _ASSET_FIELDS = ( 'name', 'value', 'purchase_price' )
    field_order   = [ 'name', 'value', 'purchase_price', 'mortgage_balance' ]

    name           = forms.CharField( label = 'Name', max_length = 100, required = False )
    value          = forms.DecimalField( label = 'Current value', min_value = 0, required = False )
    purchase_price = forms.DecimalField( label = 'Purchase price', min_value = 0, required = False )

    @staticmethod
    def _asset_initial( asset ) -> dict:
        return { 'name': asset.name, 'value': asset.opening_value,
                 'purchase_price': asset.cost_basis }

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ],
            asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
            opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ] )


@dataclass( frozen = True )
class PropertyPane:
    """Per-type configuration for a mortgaged-property pane (rentals, second homes), the single source
    consumed by both the Property-section template (the initial render) and the pane's add/edit/delete
    views (the async swaps): the form class, the holding asset class, the section heading, the DOM ids
    the async swaps target, the URL names the generic list/form partials resolve, and the list's
    wording. Holding it in one place keeps the initial render and the swaps from drifting. The handle
    stem is not here -- it lives on the form (`form._PREFIX`), the single source for minting."""

    form        : type
    asset_class : AssetClass
    heading     : str
    list_id     : str
    form_id     : str
    add_url     : str
    edit_url    : str
    delete_url  : str
    add_text    : str
    empty_text  : str

    def template_context( self ) -> dict:
        """The context the generic `property_list.html` / `property_form.html` partials render from --
        the ids, URL names, and wording (the holdings themselves are supplied by the caller)."""
        return { 'list_id': self.list_id, 'form_id': self.form_id, 'add_url': self.add_url,
                 'edit_url': self.edit_url, 'delete_url': self.delete_url,
                 'add_text': self.add_text, 'empty_text': self.empty_text }


RENTAL_PANE = PropertyPane(
    form = RentalForm, asset_class = AssetClass.REAL_ESTATE_RENTAL, heading = 'Rental properties',
    list_id = 'rentals-list', form_id = 'rentals-form',
    add_url = 'rental_add', edit_url = 'rental_edit', delete_url = 'rental_delete',
    add_text = 'Add a rental property', empty_text = 'No rental properties.' )

SECOND_HOME_PANE = PropertyPane(
    form = SecondHomeForm, asset_class = AssetClass.REAL_ESTATE_SECOND_HOME, heading = 'Second homes',
    list_id = 'second-homes-list', form_id = 'second-homes-form',
    add_url = 'second_home_add', edit_url = 'second_home_edit', delete_url = 'second_home_delete',
    add_text = 'Add a second home', empty_text = 'No second homes.' )

# The mortgaged-property panes in display order, iterated by the Property section and mapped to their
# add/edit/delete views.
PANES = ( RENTAL_PANE, SECOND_HOME_PANE )


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
