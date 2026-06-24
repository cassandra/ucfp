"""The profile-build screen: the first page that drives the form -> typed `Profile` ->
repository round-trip for a real user.

`/profile/` resolves the organization's profile (creating one if none) and redirects to its
detail page, so the view always operates on a concrete uuid. `/profile/<uuid>/` renders the
single-page form and, on POST, materializes the typed `Profile` (in the form layer) and saves
it under the current month. Pre-populating the form from an existing profile is the next step.
"""
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from .forms import ProfileBuildForm
from .repository import create_profile, latest_profile, load_profile, save_profile
from .view_mixins import ProfileViewMixin

_TEMPLATE = 'profile/pages/profile_detail.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class ProfileHomeView( View ):
    """`/profile/` -- land on the organization's latest profile, creating one if it has none."""

    def get( self, request ):
        record = latest_profile( request.organization ) or create_profile( request.organization )
        return redirect( 'profile_detail', profile_uuid = record.uuid )


@method_decorator( ensure_organization, name = 'dispatch' )
class ProfileDetailView( ProfileViewMixin, View ):
    """`/profile/<uuid>/` -- the single-page profile form (blank for now); POST saves the typed
    profile under the current month."""

    def get( self, request, *args, **kwargs ):
        record = self.get_profile( request, *args, **kwargs )
        return render( request, _TEMPLATE, {
            'form': ProfileBuildForm( profile = load_profile( record ) ) } )

    def post( self, request, *args, **kwargs ):
        self.get_profile( request, *args, **kwargs )
        form = ProfileBuildForm( request.POST )
        if form.is_valid():
            record = save_profile( request.organization, form.to_profile() )
            return redirect( 'profile_detail', profile_uuid = record.uuid )
        return render( request, _TEMPLATE, { 'form': form } )
