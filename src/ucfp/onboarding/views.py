from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import render, resolve_url
from django.utils.decorators import method_decorator
from django.views.generic import View

from custom.decorators import require_authentication_enabled

from user import collision
from user.signin_manager import SigninManager

from . import reconciliation_service


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class SigninCollisionView( View ):
    """Reconcile a signed-in Guest's in-progress plan with an existing account they have just proved
    they own (the sign-in code hands off here via ``settings.SIGNIN_COLLISION_URL``).

    The Guest is still ``request.user`` -- the sign-in code deliberately did not switch accounts yet.
    A Guest with no plan of substance is silently superseded (adopt the existing account). Otherwise we
    show a side-by-side summary of the two plans and let the person keep their current work (re-homed
    onto the existing account), keep the existing account's plan instead, or decide later (stay a
    Guest, nothing lost). The target is read from the session; ``request.user`` is the Guest.
    """

    def get( self, request, *args, **kwargs ):
        target, guest = self._collision_parties( request )
        if target is None:
            return self._done( request )

        current = reconciliation_service.organization_summary(
            reconciliation_service.sole_organization( guest ) )
        if not current.has_content:
            # Nothing worth keeping: adopt the existing account without asking.
            reconciliation_service.discard_current_keep_previous( guest, target )
            collision.clear_collision_target( request )
            return self._sign_in( request, target )

        existing = reconciliation_service.organization_summary(
            reconciliation_service.sole_organization( target ) )
        # Each option is a card the person can pick directly: keeping the current work re-homes it onto
        # the existing account; keeping the existing account's plan discards the current work.
        return render( request, 'onboarding/signin_collision.html', {
            'options': [
                { 'label': 'Your current work', 'summary': current, 'choice': 'keep_current' },
                { 'label': 'Your existing account', 'summary': existing, 'choice': 'discard_current' },
            ],
        } )

    def post( self, request, *args, **kwargs ):
        target, guest = self._collision_parties( request )
        collision.clear_collision_target( request )
        if target is None:
            return self._done( request )

        choice = request.POST.get( 'choice' )
        if choice == 'keep_current':
            reconciliation_service.keep_current_discard_previous( guest, target )
            return self._sign_in( request, target )
        if choice == 'discard_current':
            reconciliation_service.discard_current_keep_previous( guest, target )
            return self._sign_in( request, target )
        # 'decide_later' (or anything unrecognized): leave the Guest and their plan exactly as they are.
        return self._done( request )

    @staticmethod
    def _collision_parties( request ):
        """The (target account, current Guest) the collision is between, or (None, guest) when there is
        no valid pending collision to resolve (stale/missing target, or the current user is not a Guest
        distinct from the target)."""
        guest = request.user
        target_uuid = collision.peek_collision_target( request )
        if ( target_uuid is None ) or ( not guest.is_authenticated ) or ( not guest.is_guest ):
            return None, guest
        target = get_user_model().objects.filter( uuid = target_uuid ).first()
        if ( target is None ) or ( target.pk == guest.pk ):
            return None, guest
        return target, guest

    def _sign_in( self, request, target ):
        request.user = target
        SigninManager().do_login( request = request )
        return self._done( request )

    @staticmethod
    def _done( request ):
        return HttpResponseRedirect( resolve_url( settings.LOGIN_REDIRECT_URL ) )
