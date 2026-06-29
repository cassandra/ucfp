"""Views for the organization (household) settings area."""
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from .forms import OrganizationSettingsForm

_SETTINGS_TEMPLATE = 'organization/settings.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class OrganizationSettingsView( View ):
    """`/organization/settings/` -- edit the current organization's household-level settings
    (currency today). Operates on `request.organization`, resolved by `ensure_organization`."""

    def get( self, request ):
        form = OrganizationSettingsForm( organization = request.organization )
        return self._render( request, form )

    def post( self, request ):
        form = OrganizationSettingsForm( request.POST, organization = request.organization )
        if form.is_valid():
            form.apply( request.organization )
            return redirect( reverse( 'organization_settings' ) )
        return self._render( request, form )

    def _render( self, request, form ):
        return render( request, _SETTINGS_TEMPLATE, {
            'form'         : form,
            'organization' : request.organization,
        } )
