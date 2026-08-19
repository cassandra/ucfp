"""Tests for the organization view decorators (bootstrapping and auth gating)."""
import uuid
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.utils import timezone

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from ucfp.session_state import SessionState

from organization.decorators import ensure_organization, require_authenticated_user

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore


@ensure_organization
def _organization_view( request ):
    return request.organization


@ensure_organization
def _active_timezone_view( request ):
    return timezone.get_current_timezone_name()


@require_authenticated_user
def _guarded_view( request ):
    return 'reached'


def _request_for( user ):
    request = RequestFactory().get( '/' )
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
