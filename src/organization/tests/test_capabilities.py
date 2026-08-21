"""Tests for the role -> write-capability mapping."""
from django.test import SimpleTestCase

from organization.capabilities import can_write
from organization.enums import OrganizationRole


class CanWriteTest( SimpleTestCase ):

    def test_privileged_roles_may_write( self ):
        for role in ( OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER ):
            self.assertTrue( can_write( role ), role )

    def test_viewer_is_read_only( self ):
        self.assertFalse( can_write( OrganizationRole.VIEWER ) )

    def test_absent_role_is_read_only( self ):
        # No active membership resolves to no role -- the default-deny basis of the write-gate.
        self.assertFalse( can_write( None ) )
