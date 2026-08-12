import logging
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from organization.templatetags.organization_tags import household_danger_section

logging.disable(logging.CRITICAL)

User = get_user_model()


def _user( email ):
    return User.objects.create_user( email = email )


def _add_member( org, user, role ):
    return OrganizationMember.objects.create(
        organization = org, user = user, organization_role = role )


class OrganizationDeleteViewTest(TestCase):

    def _url( self, org ):
        return reverse( 'organization_delete', kwargs = { 'organization_uuid': org.uuid } )

    def test_owner_deletes_household_with_confirmation(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )

        response = self.client.post( self._url( org ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 302 )
        self.assertFalse( Organization.objects.filter( pk = org.pk ).exists() )

    def test_deletion_requires_the_typed_confirmation(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )

        response = self.client.post( self._url( org ), { 'confirm': 'nope' } )

        self.assertEqual( response.status_code, 400 )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )

    def test_non_owner_is_forbidden(self):
        owner, member_user = _user( 'o@x.test' ), _user( 'm@x.test' )
        org = Organization.objects.create_for_owner( owner, 'A' )
        _add_member( org, member_user, OrganizationRole.MEMBER )
        self.client.force_login( member_user )

        response = self.client.post( self._url( org ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 403 )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )

    def test_non_member_gets_404(self):
        user, other = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( other, 'A' )
        self.client.force_login( user )

        response = self.client.post( self._url( org ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 404 )


class OrganizationLeaveViewTest(TestCase):

    def _url( self, org ):
        return reverse( 'organization_leave', kwargs = { 'organization_uuid': org.uuid } )

    def test_co_owner_can_leave_and_household_persists(self):
        u1, u2 = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( u1, 'A' )
        _add_member( org, u2, OrganizationRole.OWNER )
        self.client.force_login( u1 )

        response = self.client.post( self._url( org ) )

        self.assertEqual( response.status_code, 302 )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )
        self.assertFalse( OrganizationMember.objects.filter( organization = org, user = u1 ).exists() )

    def test_sole_owner_cannot_leave(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )

        response = self.client.post( self._url( org ) )

        self.assertEqual( response.status_code, 400 )
        self.assertTrue( OrganizationMember.objects.filter( organization = org, user = user ).exists() )


class AccountDeleteViewTest(TestCase):

    def test_deletes_account_and_logs_out(self):
        user = _user( 'a@x.test' )
        Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )
        user_id = user.pk

        response = self.client.post( reverse( 'account_delete' ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 302 )
        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertNotIn( '_auth_user_id', self.client.session )

    def test_requires_the_typed_confirmation(self):
        user = _user( 'a@x.test' )
        Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )
        user_id = user.pk

        response = self.client.post( reverse( 'account_delete' ), { 'confirm': '' } )

        self.assertEqual( response.status_code, 400 )
        self.assertTrue( User.objects.filter( pk = user_id ).exists() )

    def test_confirmation_word_is_case_and_space_insensitive(self):
        # The HTML pattern accepts any case, and users may add stray spaces; the
        # server normalizes both, so these must all count as confirmed.
        for index, typed in enumerate( ( 'DELETE', '  Delete  ', 'delete' ) ):
            with self.subTest( typed = typed ):
                user = _user( f'confirm{index}@x.test' )
                Organization.objects.create_for_owner( user, 'A' )
                self.client.force_login( user )
                user_id = user.pk

                response = self.client.post( reverse( 'account_delete' ), { 'confirm': typed } )

                self.assertEqual( response.status_code, 302 )
                self.assertFalse( User.objects.filter( pk = user_id ).exists() )

    def test_co_owned_household_is_deleted_by_default(self):
        user, co_owner = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( user, 'Shared' )
        _add_member( org, co_owner, OrganizationRole.OWNER )
        self.client.force_login( user )
        user_id = user.pk

        response = self.client.post( reverse( 'account_delete' ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 302 )
        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertFalse( Organization.objects.filter( pk = org.pk ).exists() )

    def test_co_owned_household_is_kept_when_requested(self):
        user, co_owner = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( user, 'Shared' )
        _add_member( org, co_owner, OrganizationRole.OWNER )
        self.client.force_login( user )
        user_id = user.pk

        response = self.client.post(
            reverse( 'account_delete' ),
            { 'confirm': 'delete', 'keep_org': str( org.uuid ) } )

        self.assertEqual( response.status_code, 302 )
        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertTrue( Organization.objects.filter( pk = org.pk ).exists() )
        self.assertTrue( OrganizationMember.objects.active_owners( org ).filter( user = co_owner ).exists() )


class DangerSectionRenderTest(TestCase):

    def test_sole_owner_of_one_org_sees_combined_action(self):
        user = _user( 'a@x.test' )
        Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'user_account' ) )

        self.assertContains( response, 'Delete my account and all my data' )
        self.assertContains( response, 'data-async="modal"' )  # antinode confirm modal

    def test_multi_org_shows_per_household_controls(self):
        user = _user( 'a@x.test' )
        other_owner = _user( 'b@x.test' )
        Organization.objects.create_for_owner( user, 'A' )  # sole owner
        org_b = Organization.objects.create_for_owner( other_owner, 'B' )
        _add_member( org_b, user, OrganizationRole.MEMBER )  # plain member of B
        self.client.force_login( user )

        response = self.client.get( reverse( 'user_account' ) )

        self.assertContains( response, 'Danger zone' )
        self.assertContains( response, 'Leave' )              # the member control for B
        self.assertNotContains( response, 'and all my data' )  # not the collapsed single-org form


class DangerSectionTagTest(TestCase):
    """The household_danger_section inclusion tag, which renders nothing unless
    there is an authenticated user with at least one membership."""

    def test_no_user_is_inert(self):
        self.assertEqual( household_danger_section( None ), { 'show': False } )

    def test_anonymous_user_is_inert(self):
        self.assertEqual( household_danger_section( AnonymousUser() ), { 'show': False } )

    def test_authenticated_but_memberless_user_is_inert(self):
        # E.g. under suppressed authentication, where the shared organization has
        # no members; there is nothing to delete or leave, so show nothing.
        user = _user( 'a@x.test' )
        self.assertEqual( household_danger_section( user ), { 'show': False } )


class ConfirmModalViewTest(TestCase):
    """The antinode confirm-modal views (opened by the data-async triggers)."""

    AJAX = { 'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest' }

    def test_account_delete_confirm_lone_account_hides_the_org_name(self):
        user = _user( 'a@x.test' )
        Organization.objects.create_for_owner( user, 'Alpha' )
        self.client.force_login( user )

        response = self.client.get( reverse( 'account_delete_confirm' ), **self.AJAX )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'all your data' )
        self.assertNotContains( response, 'Alpha' )  # the auto-named lone household is not shown

    def test_account_delete_confirm_multi_org_itemizes_by_name(self):
        user = _user( 'a@x.test' )
        other = _user( 'b@x.test' )
        Organization.objects.create_for_owner( user, 'Alpha' )      # solely owned -> deleted
        org_b = Organization.objects.create_for_owner( other, 'Beta' )
        _add_member( org_b, user, OrganizationRole.MEMBER )         # left

        self.client.force_login( user )

        response = self.client.get( reverse( 'account_delete_confirm' ), **self.AJAX )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Alpha' )
        self.assertContains( response, 'Beta' )

    def test_account_delete_confirm_shows_placeholder_for_auto_named_household(self):
        user = _user( 'a@x.test' )
        other = _user( 'b@x.test' )
        Organization.objects.create_default_for_user( user )        # named user-<user.uuid>, solely owned
        org_b = Organization.objects.create_for_owner( other, 'Beta' )
        _add_member( org_b, user, OrganizationRole.MEMBER )          # a 2nd membership -> not the lone case
        self.client.force_login( user )

        response = self.client.get( reverse( 'account_delete_confirm' ), **self.AJAX )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Untitled household' )
        self.assertNotContains( response, str( user.uuid ) )   # the meaningless raw name is not shown

    def test_account_delete_confirm_co_owned_offers_keep_checkbox(self):
        user, co_owner = _user( 'a@x.test' ), _user( 'b@x.test' )
        org = Organization.objects.create_for_owner( user, 'Shared' )
        _add_member( org, co_owner, OrganizationRole.OWNER )
        self.client.force_login( user )

        response = self.client.get( reverse( 'account_delete_confirm' ), **self.AJAX )

        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'keep_org' )               # the opt-out control (JSON-escaped attrs)
        self.assertContains( response, str( org.uuid ) )          # scoped to the co-owned household
        self.assertContains( response, 'Shared' )

    def test_org_delete_confirm_owner_ok(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'Alpha' )
        self.client.force_login( user )

        response = self.client.get(
            reverse( 'organization_delete_confirm', kwargs = { 'organization_uuid': org.uuid } ),
            **self.AJAX )

        self.assertEqual( response.status_code, 200 )

    def test_org_delete_confirm_non_owner_forbidden(self):
        owner, member_user = _user( 'o@x.test' ), _user( 'm@x.test' )
        org = Organization.objects.create_for_owner( owner, 'Alpha' )
        _add_member( org, member_user, OrganizationRole.MEMBER )
        self.client.force_login( member_user )

        response = self.client.get(
            reverse( 'organization_delete_confirm', kwargs = { 'organization_uuid': org.uuid } ),
            **self.AJAX )

        self.assertEqual( response.status_code, 403 )

    def test_org_leave_confirm_member_ok(self):
        owner, member_user = _user( 'o@x.test' ), _user( 'm@x.test' )
        org = Organization.objects.create_for_owner( owner, 'Alpha' )
        _add_member( org, member_user, OrganizationRole.MEMBER )
        self.client.force_login( member_user )

        response = self.client.get(
            reverse( 'organization_leave_confirm', kwargs = { 'organization_uuid': org.uuid } ),
            **self.AJAX )

        self.assertEqual( response.status_code, 200 )

    def test_org_leave_confirm_sole_owner_rejected(self):
        user = _user( 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'Alpha' )
        self.client.force_login( user )

        response = self.client.get(
            reverse( 'organization_leave_confirm', kwargs = { 'organization_uuid': org.uuid } ),
            **self.AJAX )

        self.assertEqual( response.status_code, 400 )


@override_settings(SUPPRESS_AUTHENTICATION=True)
class SuppressedAuthDeletionTest(TestCase):
    """With no authenticated user, every deletion endpoint must reject cleanly (404)
    rather than act on the anonymous user and raise."""

    def _org_uuid(self):
        # A syntactically valid uuid is all the URL needs: the auth guard runs on
        # dispatch, before any membership lookup, so no real org is required.
        return uuid.uuid4()

    def test_account_delete_confirm_is_not_found(self):
        response = self.client.get( reverse( 'account_delete_confirm' ) )
        self.assertEqual( response.status_code, 404 )

    def test_account_delete_is_not_found(self):
        response = self.client.post( reverse( 'account_delete' ), { 'confirm': 'delete' } )
        self.assertEqual( response.status_code, 404 )

    def test_household_endpoints_are_not_found(self):
        organization_uuid = self._org_uuid()
        routes = [
            ( 'get', 'organization_delete_confirm' ),
            ( 'post', 'organization_delete' ),
            ( 'get', 'organization_leave_confirm' ),
            ( 'post', 'organization_leave' ),
        ]
        for method, name in routes:
            with self.subTest( route = name ):
                url = reverse( name, kwargs = { 'organization_uuid': organization_uuid } )
                response = getattr( self.client, method )( url )
                self.assertEqual( response.status_code, 404 )

    def test_a_signed_in_user_can_still_delete(self):
        # The gate is the absence of a user, not the setting: a real user who signs
        # in even under suppressed authentication may still delete their account.
        user = _user( 'a@x.test' )
        Organization.objects.create_for_owner( user, 'A' )
        self.client.force_login( user )
        user_id = user.pk

        response = self.client.post( reverse( 'account_delete' ), { 'confirm': 'delete' } )

        self.assertEqual( response.status_code, 302 )
        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
