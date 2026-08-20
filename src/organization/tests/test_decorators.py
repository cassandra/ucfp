"""Tests for the organization view decorators (bootstrapping, auth gating, and the write-gate)."""
import uuid
from importlib import import_module
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.utils import timezone

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from ucfp.session_state import SessionState

from organization.decorators import (
    PermitsReadonlyMutation,
    ensure_organization,
    require_authenticated_user,
)

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore


@ensure_organization
def _organization_view( request ):
    return request.organization


@ensure_organization
def _active_timezone_view( request ):
    return timezone.get_current_timezone_name()


@ensure_organization
def _write_view( request ):
    return 'wrote'


@require_authenticated_user
def _guarded_view( request ):
    return 'reached'


class _ExemptView( PermitsReadonlyMutation ):
    """A view opted out of the write-gate, for the resolver marker path."""


def _resolver_match_for( view_class ):
    """A stand-in `resolver_match` exposing a view's class, as URL resolution would."""
    return SimpleNamespace( func = SimpleNamespace( view_class = view_class ) )


def _request_for( user, method = 'get' ):
    request = getattr( RequestFactory(), method )( '/' )
    request.user = user
    request.session = _SessionStore()
    request.session_state = SessionState.from_session( request )
    return request


class EnsureOrganizationTest( TestCase ):

    def _user( self ):
        return get_user_model().objects.create_user( email = 'u@example.com' )

    def test_auto_provisions_an_owned_organization_when_user_has_none( self ):
        user = self._user()
        request = _request_for( user )
        organization = _organization_view( request )
        self.assertEqual( organization.name, f'user-{user.uuid}' )
        self.assertTrue( OrganizationMember.objects.filter(
            user = user, organization = organization,
            organization_role = OrganizationRole.OWNER, is_active = True ).exists() )
        self.assertEqual(
            request.session_state.current_organization_uuid, str( organization.uuid ) )

    def test_uses_the_users_single_existing_organization( self ):
        user = self._user()
        existing = Organization.objects.create_for_owner( user, 'Existing' )
        organization = _organization_view( _request_for( user ) )
        self.assertEqual( organization, existing )
        self.assertEqual(
            Organization.objects.filter( members__user = user ).distinct().count(), 1 )

    def test_activates_the_households_display_timezone_for_the_request( self ):
        user = self._user()
        organization = Organization.objects.create_for_owner( user, 'Household' )
        organization.display_timezone = 'America/New_York'
        organization.save( update_fields = [ 'display_timezone' ] )
        self.assertEqual( _active_timezone_view( _request_for( user ) ), 'America/New_York' )

    def test_deactivates_the_timezone_after_the_request( self ):
        # The activation is scoped to the view, so the worker thread is left on the project default
        # rather than leaking the household zone to a later request that shares the thread.
        user = self._user()
        organization = Organization.objects.create_for_owner( user, 'Household' )
        organization.display_timezone = 'America/New_York'
        organization.save( update_fields = [ 'display_timezone' ] )
        _active_timezone_view( _request_for( user ) )
        self.assertEqual( timezone.get_current_timezone_name(), settings.TIME_ZONE )

    def test_reprovisions_when_session_points_at_a_deleted_organization( self ):
        # After deleting their last household, the session still references the now-
        # gone organization; ensure_organization must self-heal to a fresh owned org
        # rather than fail, so the user is never left org-less.
        user = self._user()
        request = _request_for( user )
        request.session_state.current_organization_uuid = str( uuid.uuid4() )

        organization = _organization_view( request )

        self.assertEqual( organization.name, f'user-{user.uuid}' )
        self.assertTrue( OrganizationMember.objects.filter(
            user = user, organization = organization,
            organization_role = OrganizationRole.OWNER, is_active = True ).exists() )

    def test_reuses_the_session_selected_organization( self ):
        user = self._user()
        existing = Organization.objects.create_for_owner( user, 'Existing' )
        request = _request_for( user )
        request.session_state.current_organization_uuid = str( existing.uuid )
        organization = _organization_view( request )
        self.assertEqual( organization, existing )

    def test_multiple_memberships_resolve_to_the_owned_default( self ):
        # Formerly a NotImplementedError: a user in several organizations now lands on the
        # one they own (per default_organization_for) rather than crashing.
        user = self._user()
        host = get_user_model().objects.create_user( email = 'host@example.com' )
        joined = Organization.objects.create_for_owner( host, 'Joined' )
        joined.members.create( user = user, organization_role = OrganizationRole.MEMBER )
        owned = Organization.objects.create_for_owner( user, 'Owned' )

        organization = _organization_view( _request_for( user ) )

        self.assertEqual( organization, owned )

    def test_session_selection_of_a_non_member_organization_is_discarded( self ):
        # A stale or forged session uuid pointing at an organization the user does not belong
        # to must never grant access; resolution falls back to their default and re-persists it.
        user = self._user()
        host = get_user_model().objects.create_user( email = 'host2@example.com' )
        owned = Organization.objects.create_for_owner( user, 'Owned' )
        foreign = Organization.objects.create_for_owner( host, 'Foreign' )
        request = _request_for( user )
        request.session_state.current_organization_uuid = str( foreign.uuid )

        organization = _organization_view( request )

        self.assertEqual( organization, owned )
        self.assertEqual(
            request.session_state.current_organization_uuid, str( owned.uuid ) )


class RequireAuthenticatedUserTest( TestCase ):

    def test_anonymous_request_is_rejected_as_not_found( self ):
        request = RequestFactory().get( '/' )
        request.user = AnonymousUser()
        with self.assertRaises( Http404 ):
            _guarded_view( request )

    def test_authenticated_request_passes_through( self ):
        request = RequestFactory().get( '/' )
        request.user = get_user_model().objects.create_user( email = 'u@example.com' )
        self.assertEqual( _guarded_view( request ), 'reached' )


class WriteGateTest( TestCase ):
    """The default-deny write-gate: a read-only member's unsafe request is refused unless the view
    opts out; a writer's is allowed; safe methods always pass."""

    def _member( self, role ):
        """A user who is `role` in a shared household (a separate owner keeps the household valid), with
        that household selected in the session."""
        user  = get_user_model().objects.create_user( email = f'{role.name.lower()}@example.com' )
        owner = get_user_model().objects.create_user( email = f'owner-{role.name.lower()}@example.com' )
        organization = Organization.objects.create_for_owner( owner, 'Shared' )
        OrganizationMember.objects.create(
            organization = organization, user = user, organization_role = role )
        return user, organization

    def _request( self, user, organization, method ):
        request = _request_for( user, method = method )
        request.session_state.current_organization_uuid = str( organization.uuid )
        return request

    def test_viewer_may_read( self ):
        user, organization = self._member( OrganizationRole.VIEWER )
        request = self._request( user, organization, 'get' )
        self.assertEqual( _organization_view( request ), organization )
        self.assertFalse( request.organization_can_write )

    def test_viewer_may_not_write( self ):
        user, organization = self._member( OrganizationRole.VIEWER )
        for method in ( 'post', 'put', 'patch', 'delete' ):
            request = self._request( user, organization, method )
            with self.assertRaises( PermissionDenied ):
                _write_view( request )

    def test_owner_may_write( self ):
        user, organization = self._member( OrganizationRole.OWNER )
        request = self._request( user, organization, 'post' )
        self.assertEqual( _write_view( request ), 'wrote' )
        self.assertTrue( request.organization_can_write )

    def test_member_may_write( self ):
        user, organization = self._member( OrganizationRole.MEMBER )
        request = self._request( user, organization, 'post' )
        self.assertEqual( _write_view( request ), 'wrote' )

    def test_viewer_may_write_to_a_view_that_opts_out( self ):
        user, organization = self._member( OrganizationRole.VIEWER )
        request = self._request( user, organization, 'post' )
        request.resolver_match = _resolver_match_for( _ExemptView )
        self.assertEqual( _write_view( request ), 'wrote' )
