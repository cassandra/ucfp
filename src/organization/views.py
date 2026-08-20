"""Views for the organization (household) settings and deletion controls."""
from django.contrib.auth import logout
from django.core.exceptions import BadRequest, PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from common.async_view import ModalView

from . import deletion
from .decorators import ensure_organization, require_authenticated_user
from .forms import OrganizationSettingsForm
from .models import OrganizationMember

_SETTINGS_TEMPLATE = 'organization/settings.html'

_CONFIRM_WORD = 'delete'


def _is_confirmed( request ) -> bool:
    """Whether the destructive action was confirmed by typing the word 'delete'."""
    return request.POST.get( 'confirm', '' ).strip().lower() == _CONFIRM_WORD


def _active_membership_or_404( request, organization_uuid ) -> OrganizationMember:
    member = OrganizationMember.objects.filter(
        organization__uuid = organization_uuid,
        user = request.user,
        is_active = True,
    ).select_related( 'organization' ).first()
    if member is None:
        raise Http404( 'No such household for this user.' )
    return member


@method_decorator( ensure_organization, name = 'dispatch' )
class OrganizationSettingsView( View ):
    """`/organization/settings/` -- edit the current organization's household-level display settings
    (currency and timezone). Operates on `request.organization`, resolved by `ensure_organization`."""

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
            'households'   : self._households( request ),
        } )

    def _households( self, request ):
        """The user's active households for the switcher on this page: the current one marked, each
        other one a switch target."""
        memberships = OrganizationMember.objects.for_user(
            request.user ).select_related( 'organization' )
        return [ { 'organization' : membership.organization,
                   'role_label'   : membership.organization_role.label,
                   'is_current'   : membership.organization_id == request.organization.pk }
                 for membership in memberships ]


@method_decorator( require_authenticated_user, name = 'dispatch' )
class OrganizationSwitchView( View ):
    """POST: make `organization_uuid` the user's current organization for later requests.

    Records the selection in the session (`ensure_organization` reads it on the next request), so
    every org-scoped page that follows is resolved to the chosen household; the switched-away
    household's scoped selections are retained per organization (see
    `SessionState.set_current_organization`). A user may only switch to an organization they actively
    belong to; any other target is refused as not-found, mirroring the household delete/leave actions
    -- so a forged uuid can neither reveal nor select a household that is not theirs.

    Reloads the page the switch was triggered from (the household list on Settings today), which keeps
    the endpoint relocatable rather than tied to a fixed destination.
    """

    def post( self, request, organization_uuid ):
        membership = OrganizationMember.objects.active_membership_for(
            request.user, organization_uuid )
        if membership is None:
            raise Http404( 'No such household for this user.' )
        state = request.session_state
        state.set_current_organization( str( membership.organization.uuid ) )
        state.to_session( request )
        return self._reload( request )

    def _reload( self, request ):
        """Back to the page the switch came from; home is the fallback when the referer is missing or
        off-site."""
        referer = request.META.get( 'HTTP_REFERER' )
        if referer and url_has_allowed_host_and_scheme( referer, allowed_hosts = { request.get_host() } ):
            return redirect( referer )
        return redirect( reverse( 'home' ) )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class AccountDeleteConfirmView( ModalView ):
    """The confirm-deletion modal for the whole account, itemizing which
    households will be deleted versus left."""

    def get_template_name( self ):
        return 'organization/modals/delete_account_confirm.html'

    def get( self, request, *args, **kwargs ):
        sole_owned, co_owned, non_owned = deletion.account_deletion_disposition( request.user )
        return self.modal_response( request, context = {
            # The lone-household case (a single, solely-owned organization) needs no
            # itemization -- naming the auto-generated personal household means nothing
            # to the user; just say the account and all its data go.
            'is_lone_account' : ( len( sole_owned ) == 1 ) and ( not co_owned ) and ( not non_owned ),
            'sole_owned_orgs' : sole_owned,
            'co_owned_orgs'   : co_owned,
            'non_owned_orgs'  : non_owned,
        } )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class OrganizationDeleteConfirmView( ModalView ):
    """The confirm-deletion modal for a single household (owner only)."""

    def get_template_name( self ):
        return 'organization/modals/organization_delete_confirm.html'

    def get( self, request, organization_uuid ):
        member = _active_membership_or_404( request, organization_uuid )
        if not member.is_active_owner:
            raise PermissionDenied( 'Only an owner can delete a household.' )
        return self.modal_response( request, context = {
            'organization'  : member.organization,
            'is_sole_owner' : member.is_sole_active_owner,
        } )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class OrganizationLeaveConfirmView( ModalView ):
    """The confirm-leave modal for a single household (non-sole-owner)."""

    def get_template_name( self ):
        return 'organization/modals/organization_leave_confirm.html'

    def get( self, request, organization_uuid ):
        member = _active_membership_or_404( request, organization_uuid )
        if member.is_sole_active_owner:
            raise BadRequest( 'A sole owner cannot leave; delete the household instead.' )
        return self.modal_response( request, context = { 'organization': member.organization } )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class OrganizationDeleteView( View ):
    """POST: permanently delete a household the user owns, and all its data.

    Redirects to home afterward, which re-provisions a fresh organization if this
    left the user with none.
    """

    def post( self, request, organization_uuid ):
        member = _active_membership_or_404( request, organization_uuid )
        if not member.is_active_owner:
            raise PermissionDenied( 'Only an owner can delete a household.' )
        if not _is_confirmed( request ):
            raise BadRequest( 'Deletion was not confirmed.' )
        deletion.delete_organization( member.organization )
        return redirect( reverse( 'home' ) )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class OrganizationLeaveView( View ):
    """POST: leave a household (remove only this membership; the household stays).

    A sole owner cannot leave (they must delete the household instead); the
    guarded membership delete enforces this even if the request is forged.
    """

    def post( self, request, organization_uuid ):
        member = _active_membership_or_404( request, organization_uuid )
        if member.is_sole_active_owner:
            raise BadRequest( 'A sole owner cannot leave; delete the household instead.' )
        deletion.leave_organization( member )
        return redirect( reverse( 'home' ) )


@method_decorator( require_authenticated_user, name = 'dispatch' )
class AccountDeleteView( View ):
    """POST: permanently delete the user's account and the data that goes with it
    (households they solely own), then sign out."""

    def post( self, request ):
        if not _is_confirmed( request ):
            raise BadRequest( 'Deletion was not confirmed.' )
        # Co-owned households the user chose to keep for their other owners; every
        # other owned household is deleted by default.
        keep_organization_uuids = request.POST.getlist( 'keep_org' )
        deletion.delete_account( request.user, keep_organization_uuids = keep_organization_uuids )
        logout( request )
        return redirect( reverse( 'home' ) )
