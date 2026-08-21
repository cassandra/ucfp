"""Model signal receivers for the input layer.

The lone receiver tears down the working copy a `ScenarioExploration` owned. Because the exploration holds
a *forward* one-to-one to its WORKING `ScenarioRecord`, deleting the exploration (notably when its SAVED
`source` anchor is deleted and cascades to it) does not reach that record -- it would be left orphaned,
along with its WORKING Plans and Assumptions. A cascade delete bypasses `Model.delete()` but still emits
`post_delete`, so a signal is the one mechanism that catches every path by which an exploration can go.
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from organization.write_guard import connect_write_guard

from .models import (
    AssumptionsRecord, PlansRecord, ProfileRecord, ScenarioExploration, ScenarioRecord )

# Fail-safe backstop: refuse these organization-scoped records' persistence during a read-only member's
# request (see organization.write_guard), so a write riding a GET fails toward denied.
connect_write_guard(
    ProfileRecord, PlansRecord, AssumptionsRecord, ScenarioRecord, ScenarioExploration )


@receiver( post_delete, sender = ScenarioExploration )
def teardown_owned_working_copy( sender, instance, **kwargs ) -> None:
    """Delete the WORKING scenario the exploration owned and its WORKING Plans/Assumptions -- none of which
    is referenced by anything else, so a lingering copy is pure orphan. Guarded so the various cascade
    orderings (anchor-, component-, or org-triggered) each no-op cleanly when a row is already gone."""
    working = ScenarioRecord.objects.filter( pk = instance.working_id ).first()
    if working is None:
        return
    plans_id, assumptions_id = working.plans_id, working.assumptions_id
    working.delete()
    PlansRecord.objects.filter( pk = plans_id ).delete()
    AssumptionsRecord.objects.filter( pk = assumptions_id ).delete()
