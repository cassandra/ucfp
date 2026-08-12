import logging

from django.test import TestCase
from django.urls import reverse

from common.hash_utils import hash_with_seed
from notify.models import UnsubscribedEmail

logging.disable(logging.CRITICAL)

EMAIL = 'user@example.com'


def _url( name, email = EMAIL, token = None ):
    if token is None:
        token = hash_with_seed( email )
    return reverse( name, kwargs = { 'token': token, 'email': email } )


class EmailUnsubscribeViewTestCase(TestCase):
    # GET valid/invalid-token cases live in test_email_sender.EmailUnsubscribeViewTest;
    # here we cover the new one-click POST and idempotency.

    def test_unsubscribe_is_idempotent(self):
        UnsubscribedEmail.objects.create( email = EMAIL )
        response = self.client.get( _url( 'notify_email_unsubscribe' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertEqual( UnsubscribedEmail.objects.filter( email__iexact = EMAIL ).count(), 1 )

    def test_post_one_click_unsubscribes(self):
        response = self.client.post( _url( 'notify_email_unsubscribe' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertTrue( UnsubscribedEmail.objects.filter( email__iexact = EMAIL ).exists() )


class EmailResubscribeViewTestCase(TestCase):

    def test_get_resubscribes_and_renders(self):
        UnsubscribedEmail.objects.create( email = EMAIL )
        response = self.client.get( _url( 'notify_email_resubscribe' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertFalse( UnsubscribedEmail.objects.filter( email__iexact = EMAIL ).exists() )

    def test_invalid_token_is_rejected_and_keeps_suppression(self):
        UnsubscribedEmail.objects.create( email = EMAIL )
        response = self.client.get( _url( 'notify_email_resubscribe', token = 'bad-token' ) )
        self.assertEqual( response.status_code, 400 )
        self.assertTrue( UnsubscribedEmail.objects.filter( email__iexact = EMAIL ).exists() )

    def test_resubscribe_when_not_unsubscribed_is_fine(self):
        response = self.client.get( _url( 'notify_email_resubscribe' ) )
        self.assertEqual( response.status_code, 200 )
