"""Model signal receivers for the planning layer.

The receiver clears an exploration's transient (WORKING) runs when the exploration is deleted -- which
happens when its saved anchor is deleted out from under it (the anchor cascades to the `ScenarioExploration`
that references it). Those runs are the sandbox's throwaway history, meaningless once the exploration is
gone: the workspace no longer surfaces them and the next entry would clear them anyway, so this just keeps
their (heavy) books from lingering. The runs live in the planning layer, so this cleanup does too -- the
inputs-side receiver only tears down the exploration's owned input copies. An organization teardown cascades
these same runs itself, and the clear removes only still-present rows, so the two never collide.
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from ucfp.inputs.models import ScenarioExploration

from .explore import clear_transient_runs


@receiver( post_delete, sender = ScenarioExploration )
def clear_transient_runs_on_exploration_delete( sender, instance, **kwargs ) -> None:
    """Drop the exploration's transient runs. Filters by `organization_id` rather than dereferencing
    `instance.organization`, so it never loads a row the same cascade may be deleting."""
    clear_transient_runs( instance.organization_id )
