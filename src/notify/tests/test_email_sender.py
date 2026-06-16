import os
import tempfile

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from common.hash_utils import hash_with_seed
from notify.models import UnsubscribedEmail
from notify.email_sender import EmailData, EmailSender, UnsubscribedEmailError
from testing.view_test_base import ViewTestBase

EMAIL_CFG = dict(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.com', EMAIL_PORT=587, EMAIL_HOST_USER='u',
    DEFAULT_FROM_EMAIL='from@example.com', SERVER_EMAIL='srv@example.com',
)


def _data(to, **kw):
    return EmailData(request=None, subject_template_name='subj.txt',
                     message_text_template_name='body.txt',
                     message_html_template_name='body.html',
                     to_email_address=to, **kw)


class UnsubscribeEnforcementTest(TestCase):

    def test_blocks_unsubscribed_address(self):
        UnsubscribedEmail.objects.create(email='blocked@example.com')
        with self.assertRaises(UnsubscribedEmailError):
            EmailSender(_data('blocked@example.com'))._assert_not_unsubscribed()

    def test_allows_subscribed_address(self):
        EmailSender(_data('ok@example.com'))._assert_not_unsubscribed()   # must not raise

    def test_send_refuses_unsubscribed(self):
        UnsubscribedEmail.objects.create(email='no@example.com')
        with override_settings(**EMAIL_CFG):
            with self.assertRaises(UnsubscribedEmailError):
                EmailSender(_data('no@example.com', non_blocking=False)).send()
        self.assertEqual(len(mail.outbox), 0)


class IsEmailConfiguredTest(TestCase):

    def test_missing_setting_returns_false(self):
        with override_settings(EMAIL_HOST=''):
            self.assertFalse(EmailSender.is_email_configured())
            self.assertIn('EMAIL_HOST', EmailSender.get_missing_email_setting_names())

    def test_fully_configured_returns_true(self):
        with override_settings(**EMAIL_CFG):
            self.assertTrue(EmailSender.is_email_configured())
            self.assertEqual(EmailSender.get_missing_email_setting_names(), [])


class UnsubscribedEmailManagerTest(TestCase):

    def test_exists_by_email_is_case_insensitive(self):
        UnsubscribedEmail.objects.create(email='Case@Example.com')
        self.assertTrue(UnsubscribedEmail.objects.exists_by_email('case@example.com'))
        self.assertFalse(UnsubscribedEmail.objects.exists_by_email('other@example.com'))
        self.assertFalse(UnsubscribedEmail.objects.exists_by_email(''))

    def test_exists_by_user(self):
        user = get_user_model().objects.create_user(email='member@example.com')
        self.assertFalse(UnsubscribedEmail.objects.exists_by_user(user))
        UnsubscribedEmail.objects.create(email='member@example.com')
        self.assertTrue(UnsubscribedEmail.objects.exists_by_user(user))


class SendTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        open(os.path.join(self.tmp, 'subj.txt'), 'w').write('Hi {{ name }}')
        open(os.path.join(self.tmp, 'body.txt'), 'w').write('Hello {{ name }}')
        open(os.path.join(self.tmp, 'body.html'), 'w').write('<a href="{{ UNSUBSCRIBE_URL }}">unsub</a>')

    def _templates(self):
        templates = [dict(t) for t in dj_settings.TEMPLATES]
        templates[0]['DIRS'] = list(templates[0]['DIRS']) + [self.tmp]
        return templates

    def test_send_renders_and_injects_unsubscribe_token(self):
        with override_settings(TEMPLATES=self._templates(),
                               BASE_URL_FOR_EMAIL_LINKS='http://t', **EMAIL_CFG):
            EmailSender(_data('rcpt@example.com', template_context={'name': 'Ada'},
                              non_blocking=False)).send()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Hi Ada')
        self.assertIn('rcpt@example.com', message.to)
        self.assertIn(hash_with_seed('rcpt@example.com'), message.alternatives[0][0])


class EmailUnsubscribeViewTest(ViewTestBase):

    def test_valid_token_unsubscribes(self):
        email = 'view@example.com'
        resp = self.client.get(f'/notify/email/unsubscribe/{hash_with_seed(email)}/{email}')
        self.assertSuccessResponse(resp)
        self.assertTrue(UnsubscribedEmail.objects.filter(email=email).exists())

    def test_invalid_token_rejected(self):
        resp = self.client.get('/notify/email/unsubscribe/WRONG/x@example.com')
        self.assertEqual(resp.status_code, 400)
