"""Persistence for the planning-assumptions domain.

A `ScenarioRecord` is one named set of the user's assumptions persisted as one row: identity
and ownership as columns, the entire typed `Scenario` aggregate (`schemas.Scenario`)
serialized into the inherited `data` JSON. A user keeps many scenarios over a fixed Profile;
finer persistence seams are deferred until the shape settles.
"""
from django.db import models

from common.models import JsonDocumentModel

from organization.models import Organization


class ScenarioRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'scenarios' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'
