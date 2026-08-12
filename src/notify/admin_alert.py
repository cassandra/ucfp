"""
Coalesced administrator alerting for abuse-prevention breaches.

``alert_admin`` fires at most once per window per alert type (via
``common.alerting.should_alert``), so a repeatedly tripped limit notifies the
operator once per window instead of on every hit -- keeping the alert from
becoming its own flood. On the emitting occasion it logs at WARNING (the
reliable baseline) and, if email is configured, sends a system message to
``settings.ADMIN_ALERT_EMAIL`` (default ``SERVER_EMAIL``). That message bypasses
the unsubscribe list and the user-facing send limits, so it cannot be silenced
exactly when it is needed. The whole thing is best-effort: an alerting failure
is logged and swallowed, never propagated into the request that triggered it.
"""
import logging

from django.conf import settings

from common.alerting import should_alert

from .email_sender import EmailData, EmailSender

logger = logging.getLogger(__name__)

_SUBJECT_TEMPLATE      = 'notify/emails/admin_alert_subject.txt'
_MESSAGE_TEXT_TEMPLATE = 'notify/emails/admin_alert_message.txt'
_MESSAGE_HTML_TEMPLATE = 'notify/emails/admin_alert_message.html'

_DEFAULT_WINDOW_SECS = 60 * 60


def alert_admin( alert_type : str, detail : str, window_secs : int = _DEFAULT_WINDOW_SECS ):
    """Emit a coalesced admin alert (WARNING log + email) at most once per window
    per ``alert_type``. Best-effort: never raises into the caller."""
    try:
        if not should_alert( f'admin-alert:{alert_type}', window_secs ):
            return
        logger.warning( 'Admin alert [%s]: %s', alert_type, detail )
        _send_admin_email( alert_type, detail )
    except Exception:
        logger.warning( 'Admin alert failed for type=%s', alert_type, exc_info = True )
    return


def _admin_recipient() -> str:
    return getattr( settings, 'ADMIN_ALERT_EMAIL', '' ) or getattr( settings, 'SERVER_EMAIL', '' )


def _send_admin_email( alert_type : str, detail : str ):
    recipient = _admin_recipient()
    if not recipient or not EmailSender.is_email_configured():
        return
    email_data = EmailData(
        request                    = None,
        subject_template_name      = _SUBJECT_TEMPLATE,
        message_text_template_name = _MESSAGE_TEXT_TEMPLATE,
        message_html_template_name = _MESSAGE_HTML_TEMPLATE,
        to_email_address           = recipient,
        template_context           = { 'alert_type': alert_type, 'detail': detail },
        non_blocking               = True,
        skip_unsubscribe           = True,
    )
    EmailSender( data = email_data ).send()
    return
