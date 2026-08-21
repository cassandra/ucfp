"""The read-only write-guard backstop refuses a guarded organization record's persistence while writes
are not permitted, and leaves writers (and non-guarded models) unaffected."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TestCase

from organization.models import Organization
from organization.write_guard import writes_permitted

from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.profile.schemas import Profile


class WriteGuardBackstopTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Org' )

    def test_guarded_record_write_is_refused_when_writes_not_permitted( self ):
        # The refused write aborts its transaction (Django marks it for rollback), so the attempt is
        # wrapped in a savepoint that this test can roll back and then keep querying.
        with writes_permitted( False ), self.assertRaises( PermissionDenied ):
            with transaction.atomic():
                save_profile( self.org, Profile() )
        self.assertIsNone( latest_profile( self.org ) )         # nothing was persisted

    def test_guarded_record_delete_is_refused_when_writes_not_permitted( self ):
        save_profile( self.org, Profile() )
        record = latest_profile( self.org )
        with writes_permitted( False ), self.assertRaises( PermissionDenied ):
            with transaction.atomic():
                record.delete()
        self.assertIsNotNone( latest_profile( self.org ) )      # the record is still there

    def test_writes_persist_by_default_and_when_permitted( self ):
        save_profile( self.org, Profile() )                     # default context: permitted
        with writes_permitted( True ):
            save_profile( self.org, Profile() )
        self.assertIsNotNone( latest_profile( self.org ) )

    def test_a_non_guarded_model_is_unaffected( self ):
        # Only the registered organization-data records are guarded; unrelated writes still go through.
        with writes_permitted( False ):
            organization = Organization.objects.create( name = 'Still Writable' )
        self.assertIsNotNone( organization.pk )
