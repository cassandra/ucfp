"""View helpers for the profile pages."""
from django.shortcuts import get_object_or_404

from .models import ProfileRecord


class ProfileViewMixin:
    """Resolve the `ProfileRecord` named by the URL, scoped to the request's organization.

    Pairs with `ensure_organization` (which sets `request.organization`), so a profile owned by
    another organization 404s rather than leaks. Any view operating on a profile uuid calls
    `get_profile` instead of repeating the lookup.
    """

    def get_profile( self, request, *args, **kwargs ) -> ProfileRecord:
        return get_object_or_404(
            ProfileRecord, uuid = kwargs[ 'profile_uuid' ], organization = request.organization )
