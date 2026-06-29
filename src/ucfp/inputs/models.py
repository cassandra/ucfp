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
from django.db import models

from common.models import JsonDocumentModel

from organization.models import Organization


class ProfileRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'profiles' )
    effective_date = models.DateField( 'Effective Date' )

    def __str__( self ):
        return f'{self.label} ({self.organization}, {self.effective_date})'


class PlansRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'plans' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class AssumptionsRecord( JsonDocumentModel ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'assumptions' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'
