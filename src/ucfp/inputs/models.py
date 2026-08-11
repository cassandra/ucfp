"""Persistence for the input layer -- the Profile, Plans, and Assumptions Records in one place.

Each input Record is persisted as one row: identity and ownership as columns, the entire typed
aggregate serialized into the inherited `data` JSON. Consolidating the Records here (rather than
one per domain module) keeps the input layer's persistence in a single module.

`ProfileRecord` is month-versioned: `effective_date` is the date the facts hold as of -- a full
date (day resolution) deliberately, since the app keeps at most one profile per month and
canonicalizes the date to the first of the month (see `profile.repository`), so monthly resolution
can change without a schema migration. A profile is not assumed singular: editing saves under the
current month and retains prior months. `PlansRecord` and `AssumptionsRecord` are not versioned:
many labelled sets coexist per organization, each selected and varied at planning time.
"""
import uuid

from django.db import models

from common.labeled_enum import LabeledEnumField
from common.models import JsonDocumentModel, TimestampedModel

from organization.models import Organization

from .enums import UsageRole


class InputRecord( JsonDocumentModel ):
    """Abstract base for the input records (Profile / Plans / Assumptions / Scenario). Beyond the inherited
    domain `data`, it carries `acknowledged_sections` -- the guided-interview sections the user has seen for
    this record, held as opaque section keys. This is workflow metadata kept out of `data`, and the key set
    is robust to section churn: an unknown or removed key is simply ignored, and a missing key means the
    section is unacknowledged (so a new or re-keyed section forces a fresh look).

    Every input record is partitioned by `usage_role`: a `WORKING` copy (app-managed in the exploration
    loop, overwritten as the user tweaks and pruned automatically) or a `SAVED` one (user-managed and
    retained until deleted). It defaults to `SAVED` -- the Profile is always saved (the single current
    facts are never a working copy), and any record is retained unless the loop marks it working."""

    acknowledged_sections = models.JSONField( 'Acknowledged Sections', default = list, blank = True )
    usage_role = LabeledEnumField(
        UsageRole, verbose_name = 'Usage Role', default = str( UsageRole.SAVED ) )

    class Meta:
        abstract = True

    @property
    def acknowledged_section_keys( self ) -> set:
        """The section keys the user has acknowledged for this record."""
        return set( self.acknowledged_sections or () )

    def acknowledge( self, section_key : str ) -> None:
        """Record `section_key` as seen -- idempotent, persisting only when it is newly added."""
        if section_key in self.acknowledged_section_keys:
            return
        self.acknowledged_sections = sorted( self.acknowledged_section_keys | { section_key } )
        self.save( update_fields = [ 'acknowledged_sections', 'updated_datetime' ] )


class ProfileRecord( InputRecord ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'profiles' )
    effective_date = models.DateField( 'Effective Date' )

    def __str__( self ):
        return f'{self.label} ({self.organization}, {self.effective_date})'


class PlansRecord( InputRecord ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'plans' )

    class Meta:
        # Org-scoped list/prune by usage_role, most-recent first: organization must lead to be usable.
        indexes = [ models.Index( fields = [ 'organization', 'usage_role', 'updated_datetime' ] ) ]

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class AssumptionsRecord( InputRecord ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'assumptions' )

    class Meta:
        indexes = [ models.Index( fields = [ 'organization', 'usage_role', 'updated_datetime' ] ) ]

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class ScenarioRecord( TimestampedModel ):
    """A named combination of a Plans and an Assumptions -- the user's unit of "what I plan", run and
    explored over time. It *references* its components rather than copying them, so refining a shared Plans
    or Assumptions is reflected in every scenario that uses it (a run still snapshots the resolved inputs,
    so provenance is preserved). Deleting a component CASCADEs (not PROTECT) to the scenarios that
    reference it: a scenario is meaningless without both parts, so a dangling one is not worth keeping.

    Partitioned by `usage_role`: SAVED scenarios are the user's kept set; the single WORKING scenario per
    organization is the exploration sandbox, referencing WORKING copies of a Plans and an Assumptions that
    the user tweaks -- Save/Update writes those copies back into the referenced SAVED components
    (propagation is intended). The WORKING sandbox is owned by a `ScenarioExploration`, which holds the
    one-per-organization invariant and names the SAVED scenario the sandbox was seeded from."""

    uuid  = models.UUIDField( default = uuid.uuid4, unique = True, editable = False )
    label = models.CharField( max_length = 255 )
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'scenarios' )
    plans = models.ForeignKey(
        PlansRecord, on_delete = models.CASCADE, related_name = 'scenarios' )
    assumptions = models.ForeignKey(
        AssumptionsRecord, on_delete = models.CASCADE, related_name = 'scenarios' )
    usage_role = LabeledEnumField(
        UsageRole, verbose_name = 'Usage Role', default = str( UsageRole.SAVED ) )

    class Meta:
        indexes = [ models.Index( fields = [ 'organization', 'usage_role', 'updated_datetime' ] ) ]

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class ScenarioExploration( TimestampedModel ):
    """The organization's single in-progress exploration -- a scenario being tweaked against a saved anchor.
    It *owns* the WORKING scenario copy (the tweakable inputs) and names the SAVED `source` it was seeded
    from: the baseline a drift diff is measured against, and the default target a save writes back to. One
    per organization (the sandbox is org-level, so `organization` is unique -- this is where the
    one-working-scenario invariant now lives).

    Feature-agnostic by design: the runs an exploration produces are tagged by planning feature, but the
    exploration itself is just "a scenario under tweak", so a later feature could explore the same way.
    Deleting the `source` deletes the exploration (a variation is meaningless without its anchor, so
    `source` is never null); a `post_delete` receiver tears down the owned WORKING copy, which nothing else
    references, so a cascade leaves no orphan.

    It also records the projection *frame* its runs use -- the when-controls (start-from, duration, and
    interval) chosen on entry. This is genuine exploration state, not a per-request setting: every run
    (the initial one and each Re-run) projects over this window, so it lives with the exploration rather
    than being re-derived from the session on each request. Null only for an exploration entered before the
    frame was recorded; entry always sets it. The raw choice strings are opaque here -- the planning layer
    resolves them against the profile's effective date (see `planning.forms.resolve_frame`)."""

    organization = models.OneToOneField(
        Organization, on_delete = models.CASCADE, related_name = 'scenario_exploration' )
    working = models.OneToOneField(
        ScenarioRecord, on_delete = models.CASCADE, related_name = 'owning_exploration' )
    source  = models.ForeignKey(
        ScenarioRecord, on_delete = models.CASCADE, related_name = 'anchored_explorations' )

    frame_start_from     = models.CharField( max_length = 20, null = True, blank = True )
    frame_duration_years = models.PositiveIntegerField( null = True, blank = True )
    frame_interval       = models.CharField( max_length = 10, null = True, blank = True )

    def __str__( self ):
        return f'Exploration of {self.source.label} ({self.organization})'
