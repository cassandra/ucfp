"""Persistence for the planning-orchestration layer.

A `ProjectionRunRecord` is the captured package of one forecast: its inputs (Profile, Scenario,
run frame) and non-books result are the typed `ProjectionRun` (see `schemas`) serialized into
`data`; the books it produced are persisted via the accounts repository and referenced here by
FK. Immutable once created -- the historical record of exactly what produced a result, for
reporting and drill-down.
"""
from django.db import models

from common.models import JsonDocumentModel

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord


class ProjectionRunRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'projection_runs' )
    books = models.ForeignKey(
        BooksOfAccountRecord, on_delete = models.PROTECT, related_name = '+' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'
