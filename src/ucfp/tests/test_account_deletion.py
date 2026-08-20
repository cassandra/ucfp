"""Integration tests for account/household deletion that cross into ucfp domain
data -- financial-data cascade completeness and the post-deletion re-provision.

Lives in ucfp (not organization) so it can create real domain records: the
organization app must not depend on ucfp, but ucfp may depend on organization.
"""
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization import deletion
from organization.models import Organization, OrganizationMember

from ucfp.accounts.models import (
    AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord )
from ucfp.inputs.models import ProfileRecord
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile

logging.disable(logging.CRITICAL)

User = get_user_model()


class FinancialDataCascadeTest(TestCase):
    """Deleting an account must erase the whole financial-data chain of every
    household it solely owns -- not merely the top-level rows. A captured run
    produces books with accounts, transactions, and entries; the inputs layer
    persists the profile. All of it must be gone (right to erasure)."""

    def setUp( self ):
        # A real run reads seeded economic parameters (see planning.tests.support).
        seed_default_parameter_sets()

    def _populate( self, organization ):
        profile = forecast_profile()
        save_profile( organization, profile )
        run_and_capture(
            organization, profile, Plans(), expected_assumptions(), forecast_frame(),
            label = 'Run' )

    def test_deleting_an_organization_erases_its_full_financial_data_chain(self):
        user = User.objects.create_user( email = 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self._populate( org )
        org_id = org.pk
        # The setup really produced the deep chain, so the assertions below are meaningful.
        self.assertTrue( AccountRecord.objects.exists() )
        self.assertTrue( EntryRecord.objects.exists() )
        self.assertTrue( ProjectionRunRecord.objects.exists() )
        self.assertTrue( ProfileRecord.objects.exists() )

        deletion.delete_organization( org )

        self._assert_no_financial_data_for( org_id )

    def test_deleting_an_account_erases_its_solely_owned_financial_data_chain(self):
        user = User.objects.create_user( email = 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        self._populate( org )
        user_id, org_id = user.pk, org.pk

        deletion.delete_account( user )

        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertFalse( Organization.objects.filter( pk = org_id ).exists() )
        self._assert_no_financial_data_for( org_id )

    def _assert_no_financial_data_for( self, org_id ):
        self.assertFalse( BooksOfAccountRecord.objects.filter( organization_id = org_id ).exists() )
        self.assertFalse( ProjectionRunRecord.objects.filter( organization_id = org_id ).exists() )
        self.assertFalse( PlanningResultRecord.objects.filter( organization_id = org_id ).exists() )
        self.assertFalse( ProfileRecord.objects.filter( organization_id = org_id ).exists() )
        # The books' owned rows (accounts, transactions, entries) cascade with it; once every
        # organization is gone these tables are empty, which is the erasure guarantee.
        self.assertFalse( AccountRecord.objects.exists() )
        self.assertFalse( TransactionRecord.objects.exists() )
        self.assertFalse( EntryRecord.objects.exists() )


class PostDeletionReprovisionTest(TestCase):

    def test_deleting_the_last_household_leaves_the_user_with_a_fresh_org(self):
        user = User.objects.create_user( email = 'a@x.test' )
        org_a = Organization.objects.create_for_owner( user, 'A' )
        org_b = Organization.objects.create_for_owner( user, 'B' )
        self.client.force_login( user )

        # Delete both solely-owned households; the account is kept.
        self.client.post(
            reverse( 'organization_delete', kwargs = { 'organization_uuid': org_a.uuid } ),
            { 'confirm': 'delete' } )
        # Follow the redirect to home, which re-provisions when the user has no org.
        self.client.post(
            reverse( 'organization_delete', kwargs = { 'organization_uuid': org_b.uuid } ),
            { 'confirm': 'delete' }, follow = True )

        # The user is never left org-less: a fresh, solely-owned organization exists.
        owned = OrganizationMember.objects.for_user( user )
        self.assertEqual( owned.count(), 1 )
        self.assertTrue( owned.first().is_active_owner )
