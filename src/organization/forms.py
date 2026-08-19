"""Forms for the organization (household) settings area."""
from django import forms

from ucfp.accounts.enums import CurrencyType

from .constants import TIMEZONE_CHOICES


class OrganizationSettingsForm( forms.Form ):
    """The organization's household-level display settings: the currency all of the org's books and
    planning are denominated and shown in, and the timezone its stored (UTC) datetimes -- run
    timestamps and default run names -- are shown in. A home for further settings later."""

    currency = forms.ChoiceField(
        label   = 'Currency',
        choices = CurrencyType.choices(),
        widget  = forms.Select( attrs = { 'class': 'custom-select w-auto' } ),
    )
    timezone = forms.ChoiceField(
        label   = 'Timezone',
        choices = TIMEZONE_CHOICES,
        widget  = forms.Select( attrs = { 'class': 'custom-select w-auto' } ),
    )

    def __init__( self, *args, organization = None, **kwargs ):
        super().__init__( *args, **kwargs )
        self._organization = organization
        if ( organization is not None ) and ( not self.is_bound ):
            self.fields[ 'currency' ].initial = str( organization.currency )
            self.fields[ 'timezone' ].initial = organization.display_timezone

    def apply( self, organization ):
        """Persist the chosen currency and display timezone on `organization`."""
        organization.currency         = CurrencyType.from_name( self.cleaned_data[ 'currency' ] )
        organization.display_timezone = self.cleaned_data[ 'timezone' ]
        organization.save( update_fields = [ 'currency', 'display_timezone' ] )
        return organization
