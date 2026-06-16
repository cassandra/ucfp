from typing import Dict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import BadRequest
from django.shortcuts import render
from django.views.generic import View

from notify.email_sender import EmailSender
from testing.ui.email_test_views import EmailPreviewView

from user.signin_manager import SigninManager
from user.schemas import UserAuthenticationData


class TestUiUserHomeView( View ):

    def get(self, request, *args, **kwargs):
        return render( request, 'user/tests/ui/home.html', {} )


class TestUiViewSigninEmailView( EmailPreviewView ):

    @property
    def app_name(self):
        return 'user'

    def get_extra_context( self, email_type : str ) -> Dict[ str, object ]:
        if email_type == 'signin_magic_link':
            return {
                'magic_code': 'abc123',
                'magic_code_lifetime_minutes': 123,
            }
        return dict()


class TestUiSendSigninEmailView( View ):
    """ Actually sending emails to ensure it looks right on delivery. """

    def get( self, request, *args, **kwargs ):
        if not EmailSender.is_email_configured():
            raise NotImplementedError('Email is not configured for this server.')

        # The magic-link token is built from a real user (Django's token
        # generator reads `user.last_login`, which AnonymousUser lacks). When a
        # developer opens this dev-only link without being signed in, fall back
        # to the configured address and any existing user, purely so the email
        # renders and sends.
        User = get_user_model()
        if request.user.is_authenticated and request.user.email:
            user = request.user
            email_address = request.user.email
        else:
            email_address = settings.EMAIL_HOST_USER
            user = User.objects.filter( email = email_address ).first() or User.objects.first()
            if user is None:
                raise BadRequest( 'No user exists to build a signin token; run "manage.py bootstrap".' )

        email_type = kwargs.get('email_type')
        if email_type == 'signin_magic_link':
            user_auth_data = UserAuthenticationData(
                request = request,
                override_user = user,
                override_email = email_address,
            )
            SigninManager().send_signin_magic_link_email(
                request = request,
                user_auth_data = user_auth_data,
            )
        else:
            raise BadRequest( f'Sending email type "{email_type}" not implemented.' )

        return render( request, 'user/tests/ui/send_email_success.html' )
