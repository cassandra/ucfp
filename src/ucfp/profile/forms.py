"""Forms for the profile-build page.

These are plain forms (not ModelForms): a `ProfileRecord` is just a JSON blob, so the form
layer's job is to collect input and *materialize a typed `Profile`* -- the `ProfileBuildForm`
composite owns that mapping. It depends on the schema (presentation -> domain, the right
direction); the domain schema never depends on forms. Tracer scope: the People section (one
subject + filing status) and a few What-you-own rows; multiple subjects and dynamic add/remove
rows come later.
"""
from django import forms
from django.forms import formset_factory

from ucfp.accounts.enums import AssetClass
from ucfp.tax.enums import FilingStatus

from .schemas import PRIMARY_SUBJECT_HANDLE, AssetProfile, Profile, SubjectProfile


class PeopleForm( forms.Form ):
    """The People section: the (single) subject and the household filing status."""

    subject_name      = forms.CharField( label = 'Your name', max_length = 100 )
    subject_birthdate = forms.DateField( label = 'Your birthdate' )
    filing_status     = forms.ChoiceField( label = 'Filing status', choices = FilingStatus.choices() )


class AssetForm( forms.Form ):
    """One holding in the What-you-own section. A row with no name is treated as blank and
    skipped; a named row must give its type and value."""

    name          = forms.CharField( label = 'Name', max_length = 100, required = False )
    asset_class   = forms.ChoiceField(
        label = 'Type', choices = AssetClass.choices(), required = False )
    opening_value = forms.DecimalField( label = 'Value', required = False, min_value = 0 )
    cost_basis    = forms.DecimalField( label = 'Cost basis', required = False, min_value = 0 )

    def is_filled( self ) -> bool:
        return bool( self.cleaned_data.get( 'name' ) )

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'name' ) and (
                not cleaned.get( 'asset_class' ) or cleaned.get( 'opening_value' ) is None ):
            raise forms.ValidationError(
                'Give this holding a type and value, or clear its name to drop the row.' )
        return cleaned


AssetFormSet = formset_factory( AssetForm, extra = 3 )


class ProfileBuildForm:
    """The profile page's form group -- the People form plus the holdings formset -- and the
    assembly into a typed `Profile`.

    Bundling the sub-forms and materializing the aggregate live here, in the form layer, so the
    view stays thin and the domain schema stays free of any form knowledge. Render via its
    `people` and `holdings` attributes.
    """

    _ASSET_PREFIX = 'asset'

    def __init__( self, data = None, profile : Profile = None ):
        people_initial = self._people_initial( profile ) if profile is not None else None
        asset_initial  = self._asset_initial( profile ) if profile is not None else None
        self.people   = PeopleForm( data, initial = people_initial )
        self.holdings = AssetFormSet( data, prefix = self._ASSET_PREFIX, initial = asset_initial )

    @staticmethod
    def _people_initial( profile : Profile ) -> dict:
        initial = dict()
        if profile.subjects:
            subject = profile.subjects[ 0 ]
            initial[ 'subject_name' ]      = subject.name
            initial[ 'subject_birthdate' ] = subject.birthdate
        if profile.filing_status is not None:
            initial[ 'filing_status' ] = profile.filing_status.name.lower()
        return initial

    @staticmethod
    def _asset_initial( profile : Profile ) -> list:
        return [ {
            'name'         : asset.name,
            'asset_class'  : asset.asset_class.name.lower(),
            'opening_value': asset.opening_value,
            'cost_basis'   : asset.cost_basis,
        } for asset in profile.assets ]

    def is_valid( self ) -> bool:
        people_valid   = self.people.is_valid()
        holdings_valid = self.holdings.is_valid()
        return people_valid and holdings_valid

    def to_profile( self ) -> Profile:
        people = self.people.cleaned_data
        subject = SubjectProfile(
            handle    = PRIMARY_SUBJECT_HANDLE,
            name      = people[ 'subject_name' ],
            birthdate = people[ 'subject_birthdate' ] )
        return Profile(
            subjects      = [ subject ],
            filing_status = FilingStatus.from_name( people[ 'filing_status' ] ),
            assets        = self._assets() )

    def _assets( self ) -> list:
        assets = list()
        for index, form in enumerate( self.holdings ):
            if not form.is_filled():
                continue
            assets.append( AssetProfile(
                handle        = f'asset-{index + 1}',
                name          = form.cleaned_data[ 'name' ],
                asset_class   = AssetClass.from_name( form.cleaned_data[ 'asset_class' ] ),
                opening_value = form.cleaned_data[ 'opening_value' ],
                cost_basis    = form.cleaned_data[ 'cost_basis' ] ) )
        return assets
