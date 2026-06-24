"""View helpers for the scenario pages."""
from django.shortcuts import get_object_or_404

from .models import ScenarioRecord


class ScenarioViewMixin:
    """Resolve the `ScenarioRecord` named by the URL, scoped to the request's organization.

    Pairs with `ensure_organization` (which sets `request.organization`), so a scenario owned by
    another organization 404s rather than leaks. Any view operating on a scenario uuid calls
    `get_scenario` instead of repeating the lookup.
    """

    def get_scenario( self, request, *args, **kwargs ) -> ScenarioRecord:
        return get_object_or_404(
            ScenarioRecord, uuid = kwargs[ 'scenario_uuid' ], organization = request.organization )
