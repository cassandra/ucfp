from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from testing.base_test_case import BaseTestCase

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember
from organization.permissions import OrganizationPermissions


class OrganizationPermissionsTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.user = self.User.objects.create_user( email = 'm@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.user, name = 'Acme' )
        self.outsider = self.User.objects.create_user( email = 'out@example.com', password = 'x' )
        return

    def test_has_role_true_for_matching_role(self):
        self.assertTrue(
            OrganizationPermissions.has_role( self.user, self.organization, OrganizationRole.OWNER )
        )
        return

    def test_has_role_false_for_unmatched_role_no_hierarchy(self):
        # An OWNER does not implicitly satisfy a MEMBER-only check.
        self.assertFalse(
            OrganizationPermissions.has_role( self.user, self.organization, OrganizationRole.MEMBER )
        )
        return

    def test_has_role_accepts_multiple_roles(self):
        self.assertTrue(
            OrganizationPermissions.has_role(
                self.user, self.organization, OrganizationRole.OWNER, OrganizationRole.ADMIN
            )
        )
        return

    def test_has_role_false_for_outsider(self):
        self.assertFalse(
            OrganizationPermissions.has_role( self.outsider, self.organization, OrganizationRole.OWNER )
        )
        return

    def test_has_role_false_for_inactive_membership(self):
        # Add a second owner so the first can be deactivated without tripping the invariant.
        other = self.User.objects.create_user( email = 'o2@example.com', password = 'x' )
        OrganizationMember.objects.create(
            organization = self.organization,
            user = other,
            organization_role = OrganizationRole.OWNER,
        )
        membership = OrganizationMember.objects.get( organization = self.organization, user = self.user )
        membership.is_active = False
        membership.save()
        self.assertFalse(
            OrganizationPermissions.has_role( self.user, self.organization, OrganizationRole.OWNER )
        )
        return

    def test_get_membership_none_for_anonymous(self):
        self.assertIsNone(
            OrganizationPermissions.get_membership( AnonymousUser(), self.organization )
        )
        return


class RequireRoleDecoratorTestCase( BaseTestCase ):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.user = self.User.objects.create_user( email = 'm@example.com', password = 'x' )
        self.organization = Organization.objects.create_for_owner( self.user, name = 'Acme' )
        return

    def _build_view(self):
        @OrganizationPermissions.require_role(
            OrganizationRole.OWNER,
            organization_getter = lambda request, *args, **kwargs: self.organization,
        )
        def view( request ):
            return 'ok'
        return view

    def test_allows_when_user_has_role(self):
        request = self.create_request()
        request.user = self.user
        self.assertEqual( self._build_view()( request ), 'ok' )
        return

    def test_denies_when_user_lacks_role(self):
        outsider = self.User.objects.create_user( email = 'out@example.com', password = 'x' )
        request = self.create_request()
        request.user = outsider
        with self.assertRaises( PermissionDenied ):
            self._build_view()( request )
        return
