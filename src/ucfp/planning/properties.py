"""§3 rentals: a rental property handled as a unit.

A rental is three flat profile facts that belong together -- the holding (`AssetProfile`,
`REAL_ESTATE_RENTAL`), its gross rent (`RentalIncome`), and an optional mortgage (`LoanProfile`) --
tied by a shared property handle. This module owns creating, editing, and removing them as one, so
the rest of the app keeps seeing flat lists while the user works with a whole property. Operating
expenses attach later, in spending (§6), by the same handle.
"""
from dataclasses import replace

from django import forms

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, RealPropertyType
from ucfp.profile.schemas import AssetProfile, LoanProfile, PropertyProfile
from ucfp.scenario.schemas import LoanPrepayment


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


def delete_rental( profile, scenario, property_handle : str ):
    """Remove a rental as a unit: its holding, gross income, mortgage, the mortgage's prepayment,
    and any operating expenses attached to it."""
    mortgage = _mortgage_handle( property_handle )
    profile  = replace(
        profile,
        assets         = [ a for a in profile.assets if a.handle != property_handle ],
        rental_incomes = [ r for r in profile.rental_incomes
                           if r.property_handle != property_handle ],
        loans          = [ loan for loan in profile.loans if loan.handle != mortgage ] )
    scenario = replace(
        scenario,
        prepayments = [ p for p in scenario.prepayments if p.loan_handle != mortgage ],
        expenses    = [ e for e in scenario.expenses if e.property_handle != property_handle ] )
    return profile, scenario


class RentalForm( forms.Form ):
    """One rental property as a unit: the holding (value, basis, acquisition, owner, type) and an
    optional mortgage. `apply` writes the asset and the mortgage (plus any extra-principal
    prepayment) under one property handle -- a new one when adding, the given one when editing --
    leaving other properties intact. The gross rent is set in the Income section, not here."""

    name             = forms.CharField( label = 'Name', max_length = 100 )
    value            = forms.DecimalField( label = 'Current value', min_value = 0 )
    purchase_price   = forms.DecimalField( label = 'Purchase price', min_value = 0 )
    acquisition_date = forms.DateField( label = 'Purchase date' )
    building_basis   = forms.DecimalField(
        label = 'Building value, excludes land (for depreciation)', min_value = 0 )
    property_type    = forms.ChoiceField(
        label = 'Type', choices = [ ( kind.name, kind.label ) for kind in RealPropertyType ] )
    has_mortgage     = forms.BooleanField( label = 'There is a mortgage', required = False )
    mortgage_origination     = forms.DateField( label = 'Loan start date', required = False )
    mortgage_original_amount = forms.DecimalField(
        label = 'Original loan amount', required = False, min_value = 0 )
    mortgage_rate            = forms.DecimalField(
        label = 'Interest rate (%)', required = False, min_value = 0 )
    mortgage_term_years      = forms.IntegerField(
        label = 'Loan term (years)', required = False, min_value = 1 )
    mortgage_current_balance = forms.DecimalField(
        label = 'Balance owed now (optional)', required = False, min_value = 0 )
    mortgage_extra_principal = forms.DecimalField(
        label = 'Extra principal per month (optional)', required = False, min_value = 0 )

    def __init__( self, data = None, *, profile = None, scenario = None, handle = None ):
        super().__init__(
            data, initial = self._initial( profile, scenario, handle ) if handle else None )
        self._profile  = profile
        self._scenario = scenario
        self._handle   = handle
        self.fields[ 'owner' ] = forms.ChoiceField(
            label = 'Owner', choices = self._owner_choices( profile ) )

    @staticmethod
    def _owner_choices( profile ) -> list:
        """A lone subject is shown selected; more than one prepends a placeholder so the owner is a
        deliberate choice."""
        candidates = [ ( subject.handle, subject.name ) for subject in profile.subjects ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @classmethod
    def _initial( cls, profile, scenario, handle : str ) -> dict:
        asset = next( ( a for a in profile.assets if a.handle == handle ), None )
        if asset is None:
            return dict()
        initial = { 'name': asset.name, 'value': asset.opening_value,
                    'purchase_price': asset.cost_basis, 'owner': asset.owner_handle }
        if asset.property is not None:
            initial[ 'acquisition_date' ] = asset.property.acquisition_date
            initial[ 'building_basis' ]   = asset.property.depreciable_basis
            initial[ 'property_type' ]    = asset.property.property_type.name
        initial.update( cls._mortgage_initial( profile, scenario, handle ) )
        return initial

    @classmethod
    def _mortgage_initial( cls, profile, scenario, handle : str ) -> dict:
        mortgage = next( ( loan for loan in profile.loans
                           if loan.handle == _mortgage_handle( handle ) ), None )
        if mortgage is None:
            return dict()
        initial = {
            'has_mortgage'             : True,
            'mortgage_origination'     : mortgage.origination_date,
            'mortgage_original_amount' : mortgage.original_amount,
            'mortgage_rate'            : mortgage.interest_rate.fraction * 100,
            'mortgage_term_years'      : mortgage.original_term.months() // 12,
            'mortgage_current_balance' : mortgage.current_balance,
        }
        prepayment = next( ( p for p in scenario.prepayments
                             if p.loan_handle == _mortgage_handle( handle ) ), None )
        if prepayment is not None:
            initial[ 'mortgage_extra_principal' ] = prepayment.annual_amount / 12
        return initial

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'has_mortgage' ):
            for field, message in (
                    ( 'mortgage_origination'    , 'Enter the loan start date.' ),
                    ( 'mortgage_original_amount', 'Enter the original loan amount.' ),
                    ( 'mortgage_rate'           , 'Enter the interest rate.' ),
                    ( 'mortgage_term_years'     , 'Enter the loan term.' ) ):
                if cleaned.get( field ) is None:
                    self.add_error( field, message )
        return cleaned

    def apply( self, profile, scenario ):
        handle   = self._handle or _minted_rental_handle( profile )
        mortgage = _mortgage_handle( handle )
        assets   = self._without( profile.assets, 'handle', handle ) + [ self._asset( handle ) ]
        loans    = self._without( profile.loans, 'handle', mortgage ) + self._mortgage( handle )
        prepays  = self._without( scenario.prepayments, 'loan_handle', mortgage )
        profile  = replace( profile, assets = assets, loans = loans )
        scenario = replace( scenario, prepayments = prepays + self._prepayment( mortgage ) )
        return profile, scenario

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
        cleaned = self.cleaned_data
        if not cleaned.get( 'has_mortgage' ):
            return []
        return [ LoanProfile(
            handle = _mortgage_handle( property_handle ), name = f"{cleaned[ 'name' ]} Mortgage",
            origination_date = cleaned[ 'mortgage_origination' ],
            original_amount = cleaned[ 'mortgage_original_amount' ],
            interest_rate = Rate.percent( cleaned[ 'mortgage_rate' ] ),
            original_term = Duration( cleaned[ 'mortgage_term_years' ], TimeUnit.YEAR ),
            current_balance = cleaned.get( 'mortgage_current_balance' ),
            interest_class = ExpenseTaxClass.RENTAL_EXPENSE, property_handle = property_handle ) ]

    def _prepayment( self, mortgage_handle : str ) -> list:
        cleaned = self.cleaned_data
        extra   = cleaned.get( 'mortgage_extra_principal' )
        if not cleaned.get( 'has_mortgage' ) or not extra:
            return []
        return [ LoanPrepayment( loan_handle = mortgage_handle, annual_amount = extra * 12 ) ]
