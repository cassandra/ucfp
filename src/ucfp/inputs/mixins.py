"""View mixins for the inputs layer.

`InputGatedMixin` is the opt-in base for a view that gates on input existence: it ensures the
organization and attaches its `InputState`, so both the view and its template can branch on how much
of the Profile/Plans/Assumptions bundle is set up. A view that does not gate simply does not inherit
it (and keeps decorating its own dispatch with `ensure_organization`).
"""
from django.conf import settings
from django.utils.decorators import method_decorator

from organization.decorators import ensure_organization

from ucfp.inputs.state import completed_profile, input_state


class InputGatedMixin:
    """Base for an input-gated view: ensures `request.organization` (via `ensure_organization`) and
    attaches the organization's `InputState` as `request.input_state`, computed once per request.
    Inherit this instead of decorating dispatch with `ensure_organization` directly."""

    @method_decorator( ensure_organization )
    def dispatch( self, request, *args, **kwargs ):
        request.input_state = input_state( request.organization )
        return super().dispatch( request, *args, **kwargs )


class GuestReminderMixin:
    """Adds the Guest "don't lose your work" reminder to a data-entry view.

    It shows only once a Guest has a *complete* profile -- real work invested, yet no email and so no way
    back to it if the browser session is lost -- and never under `SUPPRESS_AUTHENTICATION`, where the data
    is the self-hosted server's rather than browser-bound. The banner is a swap panel the view refreshes
    alongside its others (via `GUEST_BANNER_TARGET`/`GUEST_BANNER_TEMPLATE`), so it appears the moment the
    profile is finished. Requires `request.organization` (an `ensure_organization` view)."""

    GUEST_BANNER_TARGET   = 'guest-email-banner'
    GUEST_BANNER_TEMPLATE = 'inputs/interview/guest_email_banner.html'

    def show_guest_reminder( self, request ) -> bool:
        return bool( ( not settings.SUPPRESS_AUTHENTICATION )
                     and request.user.is_guest
                     and completed_profile( request.organization ) )
