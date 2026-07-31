"""Deleting an organization must erase all of its data.

Financial data plus data-deletion law (right to erasure) mean an `Organization` delete has to take
every dependent record with it -- runs, their books (accounts, transactions, entries), and results --
leaving nothing orphaned. This regression guards the `PROTECT`-chain bug (#47) where a captured run's
`PROTECT` on its books blocked the whole cascade.
"""
from django.core.management import call_command
from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.models import (
    AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord )
from ucfp.inputs.plans.schemas import Plans
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord
from ucfp.planning.orchestration import run_and_capture

from .support import expected_assumptions, forecast_frame, forecast_profile


class OrganizationDeletionTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )

    def _capture_a_run( self ):
        run_and_capture(
            self.organization, forecast_profile(), Plans(), expected_assumptions(), forecast_frame(),
            label = 'Run' )

    def test_deleting_org_with_a_captured_run_erases_all_its_data( self ):
        self._capture_a_run()
        # The captured run really produced books with accounts and entries.
        self.assertEqual( ProjectionRunRecord.objects.count(), 1 )
        self.assertTrue( BooksOfAccountRecord.objects.exists() )
        self.assertTrue( AccountRecord.objects.exists() )
        self.assertTrue( EntryRecord.objects.exists() )

        self.organization.delete()

        # Right to erasure: nothing of the organization's remains.
        self.assertEqual( Organization.objects.count(), 0 )
        self.assertEqual( ProjectionRunRecord.objects.count(), 0 )
        self.assertEqual( PlanningResultRecord.objects.count(), 0 )
        self.assertEqual( BooksOfAccountRecord.objects.count(), 0 )
        self.assertEqual( AccountRecord.objects.count(), 0 )
        self.assertEqual( TransactionRecord.objects.count(), 0 )
        self.assertEqual( EntryRecord.objects.count(), 0 )
