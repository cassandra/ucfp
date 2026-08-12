import logging
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from common.redis_client import get_redis_client
from notify import admin_alert
from notify.models import UnsubscribedEmail

logging.disable(logging.CRITICAL)

EMAIL_CFG = dict(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.com', EMAIL_PORT=587, EMAIL_HOST_USER='u',
    DEFAULT_FROM_EMAIL='from@example.com', SERVER_EMAIL='srv@example.com',
    ADMIN_ALERT_EMAIL='ops@example.com',
)


class AlertAdminTestCase(TestCase):

    def setUp(self):
        get_redis_client().flushdb()
        return

    @override_settings(**EMAIL_CFG)
    def test_emits_once_then_coalesces_within_window(self):
        for _ in range(3):
            admin_alert.alert_admin('signin-per-ip', 'ip=1.2.3.4')
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**EMAIL_CFG)
    def test_distinct_alert_types_send_separately(self):
        admin_alert.alert_admin('signin-per-ip', 'x')
        admin_alert.alert_admin('verify-per-ip', 'y')
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(**EMAIL_CFG)
    def test_sends_to_admin_alert_email_with_type_in_subject(self):
        admin_alert.alert_admin('signin-global', 'ceiling hit')
        self.assertEqual(mail.outbox[0].to, ['ops@example.com'])
        self.assertIn('signin-global', mail.outbox[0].subject)

    @override_settings(**EMAIL_CFG)
    def test_bypasses_the_unsubscribe_list(self):
        UnsubscribedEmail.objects.create(email='ops@example.com')
        admin_alert.alert_admin('signin-per-ip', 'x')  # a system alert must still send
        self.assertEqual(len(mail.outbox), 1)

    def test_no_email_when_email_not_configured(self):
        # Without the email settings, is_email_configured() is False: it still
        # coalesces/logs, but sends nothing (and must not raise).
        admin_alert.alert_admin('signin-per-ip', 'x')
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(**EMAIL_CFG)
    def test_send_failure_is_swallowed(self):
        with patch.object(admin_alert, '_send_admin_email', side_effect=RuntimeError('boom')):
            admin_alert.alert_admin('signin-per-ip', 'x')  # must not raise
        self.assertEqual(len(mail.outbox), 0)
