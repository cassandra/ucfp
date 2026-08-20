import logging

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import BadRequest, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.shortcuts import render, resolve_url
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import View

from custom.decorators import require_authentication_enabled, require_verified_user
from notify.email_sender import EmailSender, UnsubscribedEmailError
from notify.views import resubscribe_url_for

from . import collision
from . import forms
from . import signin_cooldown
from . import signin_throttle
from .magic_code_generator import MagicCodeStatus, MagicCodeGenerator
from .signin_manager import SigninManager

logger = logging.getLogger(__name__)

_CODE_ENTRY_TEMPLATE = 'user/pages/magic_code.html'


def _sign_in_or_collision( request, target ):
    """Sign `target` in and land on the host's post-login page -- unless the current session is a
    *different* Guest, in which case hand off to the host's reconcile flow (via
    ``settings.SIGNIN_COLLISION_URL``) so the Guest's in-progress plan is not silently abandoned. The
    Guest remains ``request.user`` for the reconcile view to resolve."""
    current = request.user
    if current.is_authenticated and current.is_guest and ( current.pk != target.pk ):
        collision.stash_collision_target( request, target )
        return HttpResponseRedirect( resolve_url( settings.SIGNIN_COLLISION_URL ) )
    request.user = target
    SigninManager().do_login( request = request )
    return HttpResponseRedirect( resolve_url( settings.LOGIN_REDIRECT_URL ) )


def _confirm_pending_or_collision( request, account ):
    """Confirm `account`'s pending address into its verified identity and land on the post-login page --
    unless another account has claimed that address in the meantime, in which case hand off to the
    collision flow instead of crashing on the unique `email` constraint.

    The address's availability was checked when it was attached, but the unique slot can fill before the
    person confirms: the same address attached from two Guest sessions, or a different account verifying it
    first. Re-check here. Because reaching this point proves the person controls that mailbox, a now-existing
    owner is theirs: sign into it and reconcile the guest work (``_sign_in_or_collision``), dropping the moot
    pending claim -- never 500, never silently discard their proof. The ``IntegrityError`` guard closes the
    residual race between the re-check and the save."""
    User = get_user_model()
    existing = User.objects.verified_account_for_email( account.pending_email )
    if existing is None:
        try:
            account.verify_pending_email()
            return HttpResponseRedirect( resolve_url( settings.LOGIN_REDIRECT_URL ) )
        except IntegrityError:
            existing = User.objects.verified_account_for_email( account.pending_email )
            if existing is None:
                raise
    account.discard_pending_email()
    return _sign_in_or_collision( request, existing )


def _render_code_entry( request, magic_code_form, status = 200 ):
    """Render the one-time-code entry page (shared by every flow that sends a code)."""
    response = render( request, _CODE_ENTRY_TEMPLATE, { 'magic_code_form': magic_code_form } )
    response.status_code = status
    return response


def _send_magic_email_or_unsubscribed( request, user, email_address ):
    """Send `user` their magic email, or -- if the address unsubscribed -- return the
    re-enable page instead of dead-ending. Returns None when the send succeeded."""
    try:
        SigninManager().send_magic_email( request = request, user = user )
    except UnsubscribedEmailError:
        return render( request, 'user/pages/signin_unsubscribed.html', {
            'email': email_address,
            'resubscribe_url': resubscribe_url_for( email_address ),
        } )
    return None


def _account_context():
    """Context for the account page. The template branches on `request.user`'s state (Guest, with or
    without a pending claim, or Verified); this supplies only the two flags it cannot derive there:
    whether email sending is configured, and whether this is a self-hosted (SUPPRESS_AUTHENTICATION)
    deployment -- where the local Guest is the sole owner and is not solicited for an email."""
    return {
        'email_not_configured'   : not EmailSender.is_email_configured(),
        'suppress_authentication': settings.SUPPRESS_AUTHENTICATION,
    }


class RedirectAuthenticatedUserMixin:
    """Send an already-authenticated user to the home page instead of showing the sign-in form
    they don't need. A Guest counts as authenticated, so it applies here: a Guest adds an email
    through their account page, not the returning-user sign-in form."""

    def dispatch( self, request, *args, **kwargs ):
        if request.user.is_authenticated:
            return HttpResponseRedirect( reverse( 'home' ) )
        return super().dispatch( request, *args, **kwargs )


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class UserSigninView( RedirectAuthenticatedUserMixin, View ):
    """The returning-user sign-in form: enter an email to receive a one-time code/link.

    A verified account is sent a sign-in code. An unknown address is not a dead end -- it starts a
    Guest carrying that address as a pending claim, so a new visitor can begin from the sign-in page
    too; the address becomes their identity only once confirmed, never before.
    """

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

        # Abuse prevention: a throttled request neither touches an account nor sends a code, and
        # redirects to the same neutral code-entry page so it leaks no signal about the limit or email.
        if not signin_throttle.is_signin_request_allowed( request, canonical_email ):
            return HttpResponseRedirect( reverse( 'magic_code' ) )

        existing = User.objects.verified_account_for_email( canonical_email )
        if existing is None:
            # Unknown address: start a Guest tied to it (pending), so the sign-in page is a valid
            # place to begin rather than a dead end. Confirmation promotes it into a real identity.
            existing = SigninManager().start_guest_session( request )
            existing.attach_pending_email( canonical_email )

        unsubscribed = _send_magic_email_or_unsubscribed( request, existing, canonical_email )
        if unsubscribed is not None:
            return unsubscribed
        return HttpResponseRedirect( reverse( 'magic_code' ) )


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class MagicCodeView( View ):
    """The one-time-code step. GET renders the entry form (the target and code live in the session,
    so the sending views redirect here -- Post/Redirect/Get -- rather than render it in place, keeping
    the URL clean and a reload idempotent). POST consumes the code: a valid entry proves the same
    browser that requested it, and acts on the account the code was issued *for* (bound to the session,
    never the form) -- confirming a pending address (Guest -> Verified) or signing a verified one in.
    Not redirect-guarded for authenticated users, since a confirming Guest is authenticated."""

    def get( self, request, *args, **kwargs ):
        # Always render the form (no "is a code pending?" guard), so a throttled send and a real one
        # are indistinguishable here.
        return _render_code_entry( request, forms.MagicCodeForm() )

    def post( self, request, *args, **kwargs ):

        magic_code_form = forms.MagicCodeForm( request.POST )
        if not magic_code_form.is_valid():
            return _render_code_entry( request, magic_code_form, status = 400 )

        magic_code = magic_code_form.cleaned_data.get('magic_code')
        magic_code_generator = MagicCodeGenerator()

        # Abuse prevention: slow and cap code brute-forcing. Reject fast while inside the escalating
        # per-session cooldown (session only, no Redis), then the per-IP backstop against session cycling.
        if signin_cooldown.is_enabled():
            if signin_cooldown.seconds_until_allowed( request ) > 0:
                magic_code_form.add_error(
                    'magic_code', 'Too many attempts. Please wait a few seconds and try again.' )
                return _render_code_entry( request, magic_code_form, status = 429 )
            if not signin_cooldown.is_per_ip_backstop_ok( request ):
                magic_code_form.add_error(
                    'magic_code', 'Too many attempts. Please try again later.' )
                return _render_code_entry( request, magic_code_form, status = 429 )

        magic_code_status = magic_code_generator.check_magic_code( request, magic_code = magic_code )

        if magic_code_status == MagicCodeStatus.VALID:
            signin_cooldown.reset( request )
            target_uuid = magic_code_generator.magic_code_target( request )
            magic_code_generator.expire_magic_code( request )
            return self._on_valid_code( request, target_uuid )

        if magic_code_status == MagicCodeStatus.EXPIRED:
            error_message = 'Code has expired.'
        elif magic_code_status == MagicCodeStatus.INVALID:
            error_message = 'Invalid code.'
        else:
            error_message = 'Code generated an unexpected error.'

        # Count only a genuine wrong guess (INVALID) toward the cooldown/cap; an EXPIRED code is a
        # timeout, not a brute-force attempt. At the hard cap, invalidate the code so the attacker
        # must start over.
        if signin_cooldown.is_enabled() and magic_code_status == MagicCodeStatus.INVALID:
            failure_count = signin_cooldown.register_failure( request )
            if signin_cooldown.is_over_max_failures( failure_count ):
                magic_code_generator.expire_magic_code( request )
                signin_cooldown.reset( request )
                error_message = 'Too many attempts. Please start over.'

        magic_code_form.add_error( 'magic_code', error_message )
        return _render_code_entry( request, magic_code_form, status = 400 )

    def _on_valid_code( self, request, target_uuid ):
        # The target was bound to the session when the code was issued (never a client field), so a
        # valid code acts only on the account it was sent for. Its state names the intent: a pending
        # address is a Guest confirming its email (already signed in); a verified email is a returning
        # account to sign in.
        User = get_user_model()
        target = User.objects.filter( uuid = target_uuid ).first()
        if target is None:
            raise BadRequest( 'Sign-in code is no longer valid.' )

        if target.pending_email:
            return _confirm_pending_or_collision( request, target )

        return _sign_in_or_collision( request, target )


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class MagicLinkView( View ):
    """Consume a magic link (the one-click alternative to the code). It resolves the target account
    by uuid and validates the token, then acts by intent, read from that account's state:

      - a **pending** address is a Guest confirming its email -- verified only in the *same* browser
        that started the attach (else a "confirm on your original device" message), so a link that
        lands in someone else's session cannot silently hand them the account;
      - a **verified** email is a returning account -- signed in, which is safe on a valid link since
        the account is theirs by construction.
    """

    def get( self, request, user_uuid, token, *args, **kwargs ):
        User = get_user_model()
        user = User.objects.filter( uuid = user_uuid ).first()
        if user is None:
            return render( request, 'user/pages/signin_magic_bad_link.html' )
        if not PasswordResetTokenGenerator().check_token( user = user, token = token ):
            return render( request, 'user/pages/signin_magic_bad_link.html' )

        if user.pending_email:
            same_session = request.user.is_authenticated and ( request.user.pk == user.pk )
            if same_session:
                return _confirm_pending_or_collision( request, user )
            return render( request, 'user/pages/confirm_email_other_device.html',
                           { 'email': user.pending_email } )

        if user.email:
            return _sign_in_or_collision( request, user )

        return render( request, 'user/pages/signin_magic_bad_link.html' )


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class AttachEmailView( View ):
    """Attach an email to the signed-in Guest so they can recover their work, then send a confirmation
    and forward to the code page (Post/Redirect/Get). The address becomes the account's verified
    identity only once confirmed. Login-gated (a Guest is authenticated).

    If the address already belongs to a *different* verified account, the code is sent to *that* account
    so the person can prove they own it; confirming it then reconciles their guest work with it (handled
    on code verification) -- nothing is attached to the guest in that case. Otherwise the address is
    claimed as the guest's pending email, overwriting any prior claim, so a typo is fixed by re-adding."""

    def post( self, request, *args, **kwargs ):
        if request.user.is_verified:
            return HttpResponseRedirect( reverse( 'user_account' ) )

        email_address = request.POST.get('email')
        if not email_address:
            raise BadRequest( 'No email provided' )
        try:
            validate_email( email_address )
        except ValidationError:
            raise BadRequest( 'Invalid email provided' )

        User = get_user_model()
        canonical_email = User.objects.canonicalize_email( email_address )

        existing = User.objects.verified_account_for_email( canonical_email )
        if existing is not None and ( existing.pk != request.user.pk ):
            target = existing                         # prove ownership of the existing account, then reconcile
        else:
            request.user.attach_pending_email( canonical_email )
            target = request.user

        # Only send within the throttle; either way land on the code page, so a throttled attempt is
        # indistinguishable from a sent one.
        if signin_throttle.is_signin_request_allowed( request, canonical_email ):
            unsubscribed = _send_magic_email_or_unsubscribed( request, target, canonical_email )
            if unsubscribed is not None:
                return unsubscribed
        return HttpResponseRedirect( reverse( 'magic_code' ) )


class UserAccountView( View ):
    """The signed-in user's account page: a Guest is offered a single "add your email" control; a
    Verified user sees the email they sign in with. A pending, unconfirmed claim is deliberately not
    surfaced -- confirmation happens on the code page, not here. Login-gated by AuthenticationMiddleware,
    so it always has an authenticated ``request.user``."""

    def get( self, request, *args, **kwargs ):
        return render( request, 'user/pages/account.html', _account_context() )


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class ConvertToGuestView( View ):
    """Convert an Anonymous visitor into a Guest: create their email-less Guest account and log
    them in. The single conversion entry point, invoked by whichever "start using the app" control
    a page offers, so account creation lives in one place regardless of where it is triggered from.

    POST-only, so an account is created only by a deliberate submission -- a crawled GET never mints
    one. An already-signed-in visitor is left as-is (no second account); either way the visitor is
    forwarded on to begin entering data.
    """

    def post( self, request, *args, **kwargs ):
        if not request.user.is_authenticated:
            SigninManager().start_guest_session( request )
        return HttpResponseRedirect( resolve_url( settings.GUEST_START_URL ) )


@method_decorator( require_verified_user, name = 'dispatch' )
class UserSignoutView( View ):
    """Sign the current user out and return them to the site root. POST-only so a sign-out cannot be
    triggered by an incidental GET (link prefetch, an <img> src, a shared URL). Verified-only: a Guest's
    session is the sole handle to their data, so signing out would strand it -- the nav hides the control
    for a Guest, and this is the backstop against a direct request."""

    def post( self, request, *args, **kwargs ):
        logout( request )
        return HttpResponseRedirect( reverse( 'home' ) )
