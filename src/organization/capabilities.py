"""Role -> capability mapping for organization members.

`permissions.py` is the role *mechanism* (predicates over a membership); this module is the one place
that maps a role to a concrete capability. It is deliberately small -- a single read/write cut today --
but shaped to grow to finer capabilities (the ADMIN/MEMBER distinctions) without changing callers. It
depends only on the role enum, carrying no application (ucfp) concepts, so it respects the one-way
ucfp -> organization dependency and can back the write-gate in `decorators.py`.
"""
from .enums import OrganizationRole


# Roles permitted to modify an organization's data. Membership in this tuple is tested with `==` (a
# tuple `in`), so it is robust to how the role field compares. A role absent here -- and None, i.e. no
# membership -- is read-only; VIEWER is deliberately excluded. This is the default-deny basis the
# write-gate relies on.
_WRITER_ROLES = ( OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER )


def can_write( role ) -> bool:
    """Whether a member holding `role` may modify the organization's data.

    False for VIEWER and for None (no active membership) -- the read-only default the write-gate
    enforces unless a view explicitly opts out.
    """
    return role in _WRITER_ROLES
