"""§3 rentals: a rental property handled as a unit.

A rental is flat profile facts that belong together -- the holding (`AssetProfile`,
`REAL_ESTATE_RENTAL`), an optional mortgage (`LoanProfile`), and its gross rent (an `IncomeFlow`
carrying the property handle, set in the Income section) -- tied by a shared property handle. This
module owns creating, editing, and removing the property as one, so the rest of the app keeps seeing
flat lists while the user works with a whole property. Operating expenses attach in spending (§6),
and the rent in income (§5), by the same handle.
"""
from dataclasses import replace

from django import forms

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, RealPropertyType
from ucfp.environment.constants import AppConst
from ucfp.inputs.mortgage import MortgageFields
from ucfp.inputs.profile.schemas import AssetProfile, PropertyProfile
from ucfp.inputs.widgets import IsoDateInput


_RENTAL_HANDLE_PREFIX = 'rental-'


def _mortgage_handle( property_handle : str ) -> str:
    return f'{property_handle}-mortgage'


def _minted_rental_handle( profile ) -> str:
    """A fresh `rental-N` handle, the lowest index free among the profile's holdings."""
    taken = { asset.handle for asset in profile.assets }
    index = 1
    while f'{_RENTAL_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_RENTAL_HANDLE_PREFIX}{index}'


def rentals_context( profile ) -> list:
    """The rentals for the list template: each rental's handle, name, and value. The rent is set in
    the Income section, not here."""
    return [ { 'handle': asset.handle, 'name': asset.name, 'value': asset.opening_value }
             for asset in profile.assets
             if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]


def delete_rental( profile, plans, property_handle : str ):
    """Remove a rental as a unit: its holding, gross income, mortgage, the mortgage's prepayment,
    and any operating expenses attached to it."""
    mortgage = _mortgage_handle( property_handle )
    profile  = replace(
        profile,
        assets       = [ a for a in profile.assets if a.handle != property_handle ],
        income_flows = [ flow for flow in profile.income_flows
                         if flow.property_handle != property_handle ],
        loans        = [ loan for loan in profile.loans if loan.handle != mortgage ] )
    plans = replace(
        plans,
        prepayments = [ p for p in plans.prepayments if p.loan_handle != mortgage ],
        expenses    = [ e for e in plans.expenses if e.property_handle != property_handle ] )
    return profile, plans


class RentalForm( MortgageFields ):
    """One rental property as a unit: the holding (value, basis, acquisition, owner, type) and an
    optional mortgage (the shared `MortgageFields`). `apply` writes the asset and the mortgage (plus
    any extra-principal prepayment) under one property handle -- a new one when adding, the given one
    when editing -- leaving other properties intact. The gross rent is set in the Income section."""

    # Every field is optional: the form background-saves and a rental materializes only once all of
    # these are set (see `_rental_complete`), so a just-opened blank that is abandoned never appears.
    _ASSET_FIELDS = ( 'name', 'value', 'purchase_price', 'acquisition_date',
                      'building_basis', 'property_type', 'owner' )

    name             = forms.CharField( label = 'Name', max_length = 100, required = False )
    value            = forms.DecimalField( label = 'Current value', min_value = 0, required = False )
    purchase_price   = forms.DecimalField( label = 'Purchase price', min_value = 0, required = False )
    acquisition_date = forms.DateField(
        label = 'Purchase date', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
    building_basis   = forms.DecimalField(
        label = 'Building value, excludes land (for depreciation)', min_value = 0, required = False )
    property_type    = forms.ChoiceField(
        label = 'Type', required = False,
        choices = [ ( '', 'Type...' ) ] + [ ( k.name, k.label ) for k in RealPropertyType ] )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        super().__init__(
            data, initial = self._initial( profile, plans, handle ) if handle else None )
        self._profile  = profile
        self._plans = plans
        self._handle   = handle
        self.fields[ 'owner' ] = forms.ChoiceField(
            label = 'Owner', required = False, choices = self._owner_choices( profile ) )

    @staticmethod
    def _owner_choices( profile ) -> list:
        """A lone subject is shown selected; more than one prepends a placeholder so the owner is a
        deliberate choice."""
        candidates = [ ( subject.handle, subject.name ) for subject in profile.subjects ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @classmethod
    def _initial( cls, profile, plans, handle : str ) -> dict:
        asset = next( ( a for a in profile.assets if a.handle == handle ), None )
        if asset is None:
            return dict()
        initial = { 'name': asset.name, 'value': asset.opening_value,
                    'purchase_price': asset.cost_basis, 'owner': asset.owner_handle }
        if asset.property is not None:
            initial[ 'acquisition_date' ] = asset.property.acquisition_date
            initial[ 'building_basis' ]   = asset.property.depreciable_basis
            initial[ 'property_type' ]    = asset.property.property_type.name
        initial.update( cls._mortgage_initial( *cls._saved_mortgage( profile, plans, handle ) ) )
        return initial

    @staticmethod
    def _saved_mortgage( profile, plans, handle : str ):
        """This property's saved mortgage loan and its extra-principal prepayment (either may be
        None), located by the property's mortgage handle."""
        mortgage_handle = _mortgage_handle( handle )
        mortgage   = next( ( loan for loan in profile.loans
                             if loan.handle == mortgage_handle ), None )
        prepayment = next( ( p for p in plans.prepayments
                             if p.loan_handle == mortgage_handle ), None )
        return mortgage, prepayment

    @property
    def primary_fields( self ):
        """The holding fields, rendered ahead of the optional mortgage block."""
        return [ self[ name ] for name in self.fields if name not in self.MORTGAGE_FIELD_NAMES ]

    def _rental_complete( self ) -> bool:
        """All fields the rental asset needs are present -- the condition for materializing it. The
        mortgage stays non-blocking on its own (`_mortgage_complete`); there is no hard validation,
        so a partially-entered rental is simply not written rather than fighting a background save."""
        cleaned = self.cleaned_data
        return all( cleaned.get( field ) not in ( None, '' ) for field in self._ASSET_FIELDS )

    def apply( self, profile, plans ):
        handle   = self._handle or _minted_rental_handle( profile )
        mortgage = _mortgage_handle( handle )
        # Non-blocking: an incomplete rental (and so its mortgage) materializes nothing, and editing
        # an existing one to incomplete removes it; a complete rental writes its asset, mortgage, and
        # any extra-principal prepayment as a unit.
        complete = self._rental_complete()
        assets   = self._without( profile.assets, 'handle', handle ) + (
            [ self._asset( handle ) ] if complete else [] )
        loans    = self._without( profile.loans, 'handle', mortgage ) + (
            self._mortgage( handle ) if complete else [] )
        prepays  = self._without( plans.prepayments, 'loan_handle', mortgage ) + (
            self._prepayment( mortgage ) if complete else [] )
        profile  = replace( profile, assets = assets, loans = loans )
        plans = replace( plans, prepayments = prepays )
        return profile, plans

    @staticmethod
    def _without( items : list, attribute : str, value ) -> list:
        return [ item for item in items if getattr( item, attribute ) != value ]

    def _asset( self, handle : str ) -> AssetProfile:
        cleaned = self.cleaned_data
        return AssetProfile(
            handle = handle, name = cleaned[ 'name' ], asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = cleaned[ 'value' ], cost_basis = cleaned[ 'purchase_price' ],
            owner_handle = cleaned[ 'owner' ],
            property = PropertyProfile(
                acquisition_date = cleaned[ 'acquisition_date' ],
                depreciable_basis = cleaned[ 'building_basis' ],
                property_type = RealPropertyType[ cleaned[ 'property_type' ] ] ) )

    def _mortgage( self, property_handle : str ) -> list:
        loan = self._mortgage_loan(
            handle = _mortgage_handle( property_handle ),
            name = f"{self.cleaned_data[ 'name' ]} Mortgage",
            interest_class = ExpenseTaxClass.RENTAL_EXPENSE, property_handle = property_handle )
        return [ loan ] if loan is not None else []

    def _prepayment( self, mortgage_handle : str ) -> list:
        prepayment = self._mortgage_prepayment( mortgage_handle )
        return [ prepayment ] if prepayment is not None else []


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
