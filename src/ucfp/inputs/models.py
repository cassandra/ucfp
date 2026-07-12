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


class InputRecord( JsonDocumentModel ):
    """Abstract base for the input records (Profile / Plans / Assumptions). Beyond the inherited domain
    `data`, it carries `acknowledged_sections` -- the guided-interview sections the user has seen for this
    record, held as opaque section keys. This is workflow metadata kept out of `data`, and the key set is
    robust to section churn: an unknown or removed key is simply ignored, and a missing key means the
    section is unacknowledged (so a new or re-keyed section forces a fresh look)."""

    acknowledged_sections = models.JSONField( 'Acknowledged Sections', default = list, blank = True )

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

    def __str__( self ):
        return f'{self.label} ({self.organization})'


class AssumptionsRecord( InputRecord ):
    organization = models.ForeignKey(
        Organization, on_delete = models.CASCADE, related_name = 'assumptions' )

    def __str__( self ):
        return f'{self.label} ({self.organization})'
