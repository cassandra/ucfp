"""Forms for the organization (household) settings area."""
from django import forms

from ucfp.accounts.enums import CurrencyType


class OrganizationSettingsForm( forms.Form ):
    """The organization's household-level settings. Currency today (the single currency all of the
    org's books and planning are denominated and displayed in); a home for further settings later."""

    currency = forms.ChoiceField(
        label   = 'Currency',
        choices = CurrencyType.choices(),
        widget  = forms.Select( attrs = { 'class': 'custom-select w-auto' } ),
    )

    def __init__( self, *args, organization = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self._organization = organization
        if ( organization is not None ) and ( not self.is_bound ):
            self.fields[ 'currency' ].initial = str( organization.currency )

    def apply( self, organization ):
        """Persist the chosen currency on `organization`."""
        organization.currency = CurrencyType.from_name( self.cleaned_data[ 'currency' ] )
        organization.save( update_fields = [ 'currency' ] )
        return organization
