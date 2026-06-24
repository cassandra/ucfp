"""Persistence for the curated parameter-set library.

A `ParameterSet` is one named, kind-tagged set of curated parameters -- a system default (no
owning organization) or, later, an organization's copy. `data` holds the typed payload for the
kind (see `schemas` / `registry`) serialized to JSON; `seeded_data` records what the seed last
wrote, so the seed command can tell an admin-modified set (preserve) from an untouched one
(refresh for free). Identified within a kind by its `label` (the inherited name).
"""
from django.db import models

from common.labeled_enum import LabeledEnumField
from common.models import JsonDocumentModel

from organization.models import Organization

from .enums import ParameterSetKind


class ParameterSet( JsonDocumentModel ):
    kind = LabeledEnumField( ParameterSetKind, verbose_name = 'Kind' )
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'parameter_sets',
        null = True, blank = True )
    seeded_data = models.JSONField( null = True, blank = True )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields = [ 'kind', 'organization', 'label' ],
                name = 'parameter_set_unique_kind_owner_label' ),
        ]

    def __str__( self ):
        owner = self.organization if self.organization_id is not None else 'system'
        return f'{self.kind.label} "{self.label}" ({owner})'

    @property
    def is_modified( self ) -> bool:
        """Whether the live `data` differs from what the seed last wrote -- an admin has adjusted
        it, so a re-seed must preserve it rather than refresh it."""
        return self.data != self.seeded_data
