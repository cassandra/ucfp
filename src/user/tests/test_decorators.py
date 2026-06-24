"""Tests for the ensure_organization view decorator (organization bootstrapping)."""
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from ucfp.session_state import SessionState
from user.decorators import ensure_organization

_SessionStore = import_module( settings.SESSION_ENGINE ).SessionStore


@ensure_organization
def _organization_view( request ):
    return request.organization


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

    def test_reuses_the_session_selected_organization( self ):
        user = self._user()
        existing = Organization.objects.create_for_owner( user, 'Existing' )
        request = _request_for( user )
        request.session_state.current_organization_uuid = str( existing.uuid )
        organization = _organization_view( request )
        self.assertEqual( organization, existing )
