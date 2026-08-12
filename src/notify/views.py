import logging

from django.core.exceptions import BadRequest
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from common.hash_utils import hash_with_seed

from .models import UnsubscribedEmail

logger = logging.getLogger(__name__)


def _validated_email( token, email ):
    """Return the email if the token authenticates it, else raise BadRequest.

    A pseudo-secure hash keyed on a secret seed, so a stranger cannot un/
    resubscribe an arbitrary address, yet the owner needs no login to act on the
    link we email them.
    """
    if not email or not token:
        raise BadRequest( 'Improperly formed url.' )
    if hash_with_seed( email ) != token:
        raise BadRequest( 'Invalid url.' )
    return email


def resubscribe_url_for( email : str ) -> str:
    """The re-enable link for an email (its token is the same seeded hash)."""
    return reverse( 'notify_email_resubscribe',
                    kwargs = { 'token': hash_with_seed( email ), 'email': email } )


@method_decorator( csrf_exempt, name = 'dispatch' )
class EmailUnsubscribeView( View ):
    """Unsubscribe an email from all mail. GET renders a confirmation page (with a
    re-enable link); POST supports one-click unsubscribe (RFC 8058) triggered from
    the List-Unsubscribe header -- mail providers send that without a CSRF token,
    so the view is CSRF-exempt and relies on the URL token as the authenticator."""

    SUCCESS_PAGE_TEMPLATE_NAME = 'notify/pages/email_unsubscribe_success.html'

    def get( self, request, *args, **kwargs ):
        email = _validated_email( kwargs.get('token'), kwargs.get('email') )
        UnsubscribedEmail.objects.unsubscribe( email )
        context = { 'email': email, 'resubscribe_url': resubscribe_url_for( email ) }
        return render( request, self.SUCCESS_PAGE_TEMPLATE_NAME, context )

    def post( self, request, *args, **kwargs ):
        email = _validated_email( kwargs.get('token'), kwargs.get('email') )
        UnsubscribedEmail.objects.unsubscribe( email )
        return HttpResponse( status = 200 )


class EmailResubscribeView( View ):
    """Re-enable email for an address that had unsubscribed -- so someone who
    unsubscribed to stop an email flood can restore their own sign-in access."""

    SUCCESS_PAGE_TEMPLATE_NAME = 'notify/pages/email_resubscribe_success.html'

    def get( self, request, *args, **kwargs ):
        email = _validated_email( kwargs.get('token'), kwargs.get('email') )
        UnsubscribedEmail.objects.resubscribe( email )
        return render( request, self.SUCCESS_PAGE_TEMPLATE_NAME, { 'email': email } )
