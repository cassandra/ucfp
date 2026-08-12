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

from ucfp.accounts.models import BooksOfAccountRecord

logging.disable(logging.CRITICAL)

User = get_user_model()


class FinancialDataCascadeTest(TestCase):

    def test_deleting_an_organization_removes_its_financial_data(self):
        user = User.objects.create_user( email = 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        BooksOfAccountRecord.objects.create( organization = org )
        org_id = org.pk

        deletion.delete_organization( org )

        self.assertFalse( BooksOfAccountRecord.objects.filter( organization_id = org_id ).exists() )

    def test_deleting_an_account_removes_its_solely_owned_financial_data(self):
        user = User.objects.create_user( email = 'a@x.test' )
        org = Organization.objects.create_for_owner( user, 'A' )
        BooksOfAccountRecord.objects.create( organization = org )
        user_id, org_id = user.pk, org.pk

        deletion.delete_account( user )

        self.assertFalse( User.objects.filter( pk = user_id ).exists() )
        self.assertFalse( Organization.objects.filter( pk = org_id ).exists() )
        self.assertFalse( BooksOfAccountRecord.objects.filter( organization_id = org_id ).exists() )


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
