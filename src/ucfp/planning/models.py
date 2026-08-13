"""Persistence for the planning-orchestration layer.

A `ProjectionRunRecord` is the captured package of one engine run: its inputs (Profile, Plans,
Assumptions, run frame) and non-books result are the typed `ProjectionRun` (see `schemas`)
serialized into `data`; the books it produced are persisted via the accounts repository and
referenced here by FK. It is deliberately *feature-agnostic* -- the same drill-down serves every
perspective.

A `PlanningResultRecord` is the feature-facing wrapper: it tags an engine run with the planning
feature that produced it, so a feature lists and presents only its own results while reusing the
shared run views. Financial Forecasting is the degenerate case -- one run per result -- so a result
holds a single `run` FK; a sweeping feature's per-run comparison data lands in the inherited `data`
JSON later. A run's captured inputs, books, and result are immutable once created; only its user-facing
`label` is editable (a run can be renamed), which is why the scenario it came from is preserved separately.
"""
from django.db import models

from common.encrypted_fields import EncryptedJsonDocumentModel
from common.labeled_enum import LabeledEnumField

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.enums import UsageRole

from .enums import PlanningFeature


class ProjectionRunRecord( EncryptedJsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'projection_runs' )
    # CASCADE (not PROTECT): a run captured its books, and an organization's teardown deletes both,
    # so a run must not block the deletion of the books it references (right-to-erasure, #47).
    books = models.ForeignKey(
        BooksOfAccountRecord, on_delete = models.CASCADE, related_name = '+' )
    # The name of the scenario that produced this run, captured at run time. `label` starts equal to it,
    # but a run can be renamed, so this preserves the provenance the title would then no longer carry.
    # Null for a run captured before this was recorded.
    source_label = models.CharField( max_length = 255, null = True, blank = True )

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class PlanningResultRecord( EncryptedJsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'planning_results' )
    feature = LabeledEnumField( PlanningFeature, verbose_name = 'Feature' )
    run = models.ForeignKey(
        ProjectionRunRecord, on_delete = models.CASCADE, related_name = 'results' )
    # WORKING results are the exploration loop's transient runs (pruned by recency); SAVED are the ones
    # the user kept. Defaults to SAVED so an unmarked run is retained.
    usage_role = LabeledEnumField(
        UsageRole, verbose_name = 'Usage Role', default = str( UsageRole.SAVED ) )

    class Meta:
        # Org-scoped list/prune by usage_role, most-recent first: organization must lead to be usable.
        indexes = [ models.Index( fields = [ 'organization', 'usage_role', 'updated_datetime' ] ) ]

    def __str__( self ):
        return f'{self.feature.label}: {self.label} ({self.organization})'
