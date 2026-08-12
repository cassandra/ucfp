import logging

from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import User as UserType
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import BadRequest, ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import View

from notify.email_sender import EmailSender, UnsubscribedEmailError
from notify.views import resubscribe_url_for

from . import forms
from . import signin_cooldown
from . import signin_throttle
from .magic_code_generator import MagicCodeStatus, MagicCodeGenerator
from .signin_manager import SigninManager
from .schemas import UserAuthenticationData

logger = logging.getLogger(__name__)


class RedirectAuthenticatedUserMixin:
    """Send an already-authenticated user to the home page instead of showing a
    sign-in step they don't need. Applied to the interactive entry points of the
    flow (the sign-in form and the code page); the internal, non-dispatched calls
    that render the code page mid-flow are unaffected.
    """

    def dispatch( self, request, *args, **kwargs ):
        if request.user.is_authenticated:
            return HttpResponseRedirect( reverse( 'home' ) )
        return super().dispatch( request, *args, **kwargs )


class UserSigninView( RedirectAuthenticatedUserMixin, View ):

    def get(self, request, *args, **kwargs):
        context = {
            'email_not_configured': not EmailSender.is_email_configured(),
        }
        return render( request, 'user/pages/signin.html', context )

    def post(self, request, *args, **kwargs):
        email_address = request.POST.get('email')
        if not email_address:
            raise BadRequest( 'No email provided' )

        try:
            validate_email( email_address )
        except ValidationError:
            raise BadRequest( 'Invalid email provided' )

        User = get_user_model()
        canonical_email = User.objects.canonicalize_email( email_address )

        # Abuse prevention: a throttled request neither creates an account nor
        # sends a code, and returns the same neutral "check your email" response
        # so it leaks no signal about the limit (or the email) to an attacker.
        if not signin_throttle.is_signin_request_allowed( request, canonical_email ):
            return SigninMagicCodeView().get_response(
                request = request,
                magic_code_form = forms.SigninMagicCodeForm(
                    initial = { 'email_address': canonical_email }
                ),
            )

        # Sign-in is passwordless and account creation happens here: an unknown
        # email becomes a new account rather than a dead end, since the email is
        # simply the stable identifier we tie a person's plan to.
        user, created = User.objects.get_or_create_by_email( canonical_email )
        logger.debug( f'{"Created" if created else "Found"} user with email: {user.email}' )
        return SendMagicLinkEmailView().send_signin_magic_link(
            request = request,
            override_user = user,
        )


class SendMagicLinkEmailView( View ):

    def send_signin_magic_link( self,
                                request        : HttpRequest,
                                override_user  : UserType      = None ):

        user_auth_data = UserAuthenticationData(
            request = request,
            override_user = override_user,
        )
        try:
            SigninManager().send_signin_magic_link_email(
                request = request,
                user_auth_data = user_auth_data,
            )
        except UnsubscribedEmailError:
            # The code email is suppressed because this address unsubscribed.
            # Don't dead-end silently: offer the (victim-controlled) re-enable path.
            return render( request, 'user/pages/signin_unsubscribed.html', {
                'email': user_auth_data.email_address,
                'resubscribe_url': resubscribe_url_for( user_auth_data.email_address ),
            } )
        return SigninMagicCodeView().get_response(
            request = request,
            magic_code_form = user_auth_data.magic_code_form,
        )


class SigninMagicCodeView( RedirectAuthenticatedUserMixin, View ):

    TEMPLATE_NAME = 'user/pages/magic_code_signin.html'

    def get_response( self,
                      request          : HttpRequest,
                      magic_code_form  : forms.SigninMagicCodeForm,
                      status           : int                           = 200 ):
        context = {
            'magic_code_form': magic_code_form,
        }
        response = render( request, self.TEMPLATE_NAME, context )
        response.status_code = status
        return response

    def post( self, request, *args, **kwargs ):

        magic_code_form = forms.SigninMagicCodeForm( request.POST )
        if not magic_code_form.is_valid():
            return self.get_response( request, magic_code_form = magic_code_form, status = 400 )

        email_address = magic_code_form.cleaned_data.get('email_address')
        magic_code = magic_code_form.cleaned_data.get('magic_code')

        User = get_user_model()
        canonical_email = User.objects.canonicalize_email( email_address )
        try:
            existing_user = User.objects.get( email = canonical_email )
        except User.DoesNotExist:
            raise BadRequest( 'Email is invalid.' )

        magic_code_generator = MagicCodeGenerator()

        # Abuse prevention: slow and cap code brute-forcing. Reject fast while
        # inside the escalating per-session cooldown (checked first -- session
        # only, no Redis), then apply the per-IP backstop against session cycling.
        if signin_cooldown.is_enabled():
            if signin_cooldown.seconds_until_allowed( request ) > 0:
                magic_code_form.add_error(
                    'magic_code', 'Too many attempts. Please wait a few seconds and try again.' )
                return self.get_response( request, magic_code_form = magic_code_form, status = 429 )
            if not signin_cooldown.is_per_ip_backstop_ok( request ):
                magic_code_form.add_error(
                    'magic_code', 'Too many attempts. Please try again later.' )
                return self.get_response( request, magic_code_form = magic_code_form, status = 429 )

        magic_code_status = magic_code_generator.check_magic_code( request, magic_code = magic_code )
        logger.debug( f'Signin Magic: Email={email_address}, Status={magic_code_status}' )

        if magic_code_status == MagicCodeStatus.VALID:
            signin_cooldown.reset( request )
            request.user = existing_user
            SigninManager().do_login( request = request, verified_email = True )
            magic_code_generator.expire_magic_code( request )
            return HttpResponseRedirect( reverse( 'home' ) )

        if magic_code_status == MagicCodeStatus.EXPIRED:
            error_message = 'Sign-in code has expired.'
        elif magic_code_status == MagicCodeStatus.INVALID:
            error_message = 'Invalid sign-in code.'
        else:
            error_message = 'Sign-in code generated an unexpected error.'

        # Count only a genuine wrong guess (INVALID) toward the cooldown/cap; an
        # EXPIRED code is a timeout, not a brute-force attempt. At the hard cap,
        # invalidate the code so the attacker must start a fresh sign-in.
        if signin_cooldown.is_enabled() and magic_code_status == MagicCodeStatus.INVALID:
            failure_count = signin_cooldown.register_failure( request )
            if signin_cooldown.is_over_max_failures( failure_count ):
                magic_code_generator.expire_magic_code( request )
                signin_cooldown.reset( request )
                error_message = 'Too many attempts. Please start a new sign-in.'

        magic_code_form.add_error( 'magic_code', error_message )
        return self.get_response( request, magic_code_form = magic_code_form, status = 400 )


class SigninMagicLinkView( View ):
    """ This is the view for the links we include in emails for logging in. """

    def get( self, request, *args, **kwargs ):

        token = kwargs.get('token')
        email_address = kwargs.get('email')

        if not token or not email_address:
            raise BadRequest( 'Malformed request.' )

        User = get_user_model()
        canonical_email = User.objects.canonicalize_email( email_address )
        try:
            existing_user = User.objects.get( email = canonical_email )
        except User.DoesNotExist:
            raise BadRequest( 'Email is not valid.' )

        # We re-purpose the clever way tokens are used for password resets in Django.
        token_generator = PasswordResetTokenGenerator()
        is_valid = token_generator.check_token( user = existing_user, token = token )

        logger.debug( f'Signin Magic Link: EMAIL = {email_address}, VALID = {is_valid}' )

        if not is_valid:
            return render( request, 'user/pages/signin_magic_bad_link.html' )

        request.user = existing_user
        SigninManager().do_login( request = request, verified_email = True )

        url = reverse( 'home' )
        return HttpResponseRedirect( url )


class UserAccountView( View ):
    """The signed-in user's account page. Minimal for now -- it shows the email we
    identify them by; it is the future home for data export/deletion and other
    account controls. Login-gated by AuthenticationMiddleware (not on the public
    allow-list), so it always has an authenticated ``request.user``."""

    def get( self, request, *args, **kwargs ):
        return render( request, 'user/pages/account.html', {} )


class UserSignoutView( View ):
    """Sign the current user out and return them to the site root. POST-only so a
    sign-out cannot be triggered by an incidental GET (link prefetch, an <img> src,
    a shared URL)."""

    def post( self, request, *args, **kwargs ):
        logout( request )
        return HttpResponseRedirect( reverse( 'home' ) )
