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
JSON later. Both are immutable once created.
"""
from django.db import models

from common.labeled_enum import LabeledEnumField
from common.models import JsonDocumentModel

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord

from .enums import PlanningFeature


class ProjectionRunRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'projection_runs' )
    # CASCADE (not PROTECT): a run captured its books, and an organization's teardown deletes both,
    # so a run must not block the deletion of the books it references (right-to-erasure, #47).
    books = models.ForeignKey(
        BooksOfAccountRecord, on_delete = models.CASCADE, related_name = '+' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class PlanningResultRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'planning_results' )
    feature = LabeledEnumField( PlanningFeature, verbose_name = 'Feature' )
    run = models.ForeignKey(
        ProjectionRunRecord, on_delete = models.CASCADE, related_name = 'results' )

    def __str__( self ):
        return f'{self.feature.label}: {self.label} ({self.organization})'
