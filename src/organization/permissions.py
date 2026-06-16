"""Role-membership helpers for consuming applications.

`OrganizationPermissions` is the *mechanism* for role-based access: a predicate
and a view decorator that report whether a user holds a given role in an
organization. Mapping roles to concrete capabilities, and resolving which
organization a request targets, are the application's responsibility.
"""
from functools import wraps
from typing import Callable

from django.contrib.auth.models import User as UserType
from django.core.exceptions import PermissionDenied

from .enums import OrganizationRole
from .models import Organization, OrganizationMember


class OrganizationPermissions:

    @classmethod
    def get_membership( cls,
                        user         : UserType,
                        organization : Organization ) -> OrganizationMember:
        """Return `user`'s active membership in `organization`, or None."""
        if ( user is None ) or ( not user.is_authenticated ):
            return None
        return OrganizationMember.objects.filter(
            organization = organization,
            user = user,
            is_active = True,
        ).first()

    @classmethod
    def has_role( cls,
                  user         : UserType,
                  organization : Organization,
                  *roles       : OrganizationRole ) -> bool:
        """True if `user` has an active membership in `organization` with one of
        `roles`.

        Role hierarchy is deliberately not assumed: pass every acceptable role
        explicitly (an OWNER does not implicitly satisfy an ADMIN-or-MEMBER
        check).
        """
        membership = cls.get_membership( user, organization )
        if membership is None:
            return False
        return bool( membership.organization_role in roles )

    @classmethod
    def require_role( cls,
                      *roles              : OrganizationRole,
                      organization_getter : Callable ) -> Callable:
        """Build a view decorator that requires one of `roles` in the
        organization that `organization_getter(request, *args, **kwargs)`
        resolves.

        The application supplies `organization_getter` because resolving the
        target organization from a request is application-specific. Raises
        PermissionDenied when the role requirement is not met.
        """
        def decorator( view_func ):
            @wraps( view_func )
            def wrapper( request, *args, **kwargs ):
                organization = organization_getter( request, *args, **kwargs )
                if not cls.has_role( request.user, organization, *roles ):
                    raise PermissionDenied()
                return view_func( request, *args, **kwargs )
            return wrapper
        return decorator
