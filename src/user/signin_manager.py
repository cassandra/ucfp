import logging

from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.http import HttpRequest
from django.urls import reverse

from common.singleton import Singleton
from notify.email_sender import EmailData, EmailSender

from .magic_code_generator import MagicCodeGenerator

logger = logging.getLogger(__name__)


class SigninManager( Singleton ):

    MAGIC_SUBJECT_TEMPLATE_NAME = 'user/emails/signin_magic_link_subject.txt'
    MAGIC_MESSAGE_TEXT_TEMPLATE_NAME = 'user/emails/signin_magic_link_message.txt'
    MAGIC_MESSAGE_HTML_TEMPLATE_NAME = 'user/emails/signin_magic_link_message.html'

    def __init_singleton__(self):
        return

    def send_magic_email( self, request : HttpRequest, user ):
        """Email `user` a one-time code and a link to get them in -- the single "here is your
        access proof" send, whichever flow needs it. It targets the pending address when one is
        in flight (confirming a Guest's email), else the verified `email` (signing a returning
        account in). The code lives in the session, so it works only in this browser; the link
        carries a token and is resolved by intent on the receiving side (MagicLinkView).
        """
        to_email_address = user.pending_email or user.email
        token = PasswordResetTokenGenerator().make_token( user )
        magic_code = MagicCodeGenerator().make_magic_code( request, target = user.uuid )
        page_url = request.build_absolute_uri(
            reverse( 'magic_link', kwargs = { 'user_uuid': user.uuid_str, 'token': token } )
        )
        email_template_context = {
            'page_url': page_url,
            'magic_code': magic_code,
            'magic_code_lifetime_minutes': MagicCodeGenerator.get_timeout_seconds() // 60,
        }
        email_sender_data = EmailData(
            request = request,
            subject_template_name = self.MAGIC_SUBJECT_TEMPLATE_NAME,
            message_text_template_name = self.MAGIC_MESSAGE_TEXT_TEMPLATE_NAME,
            message_html_template_name = self.MAGIC_MESSAGE_HTML_TEMPLATE_NAME,
            to_email_address = to_email_address,
            template_context = email_template_context,
            non_blocking = True,
        )
        EmailSender( data = email_sender_data ).send()
        return

    def start_guest_session( self, request : HttpRequest ):
        """Convert an Anonymous visitor into a Guest: create an email-less Guest account and log
        them in. The single mechanism behind every "start using the app" entry point, so account
        creation happens in exactly one place -- callers decide *when* (a deliberate action), not
        *how*. Returns the new Guest."""
        request.user = get_user_model().objects.create_guest()
        self.do_login( request = request )
        return request.user

    def do_login( self, request ):
        django_login( request, request.user )
        return
