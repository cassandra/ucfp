"""Persistence for the financial-facts domain.

A `ProfileRecord` is the user's full set of facts persisted as one row: identity and
ownership as columns, the entire typed `Profile` aggregate (`schemas.Profile`) serialized
into the inherited `data` JSON.

`effective_date` is the date the facts hold as of. It is a full date (day resolution) in the
database deliberately: the app keeps at most one profile per month and canonicalizes the date
to the first of the month (see `repository`), so that monthly policy can change -- to a finer
or coarser resolution -- without a schema migration. A profile is not assumed singular: editing
saves under the current month and retains prior months, and later "what if" variations add more
per owner.
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
