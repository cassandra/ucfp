"""View mixins for the inputs layer.

`InputGatedMixin` is the opt-in base for a view that gates on input existence: it ensures the
organization and attaches its `InputState`, so both the view and its template can branch on how much
of the Profile/Plans/Assumptions bundle is set up. A view that does not gate simply does not inherit
it (and keeps decorating its own dispatch with `ensure_organization`).
"""
from django.utils.decorators import method_decorator

from organization.decorators import ensure_organization

from ucfp.inputs.state import input_state


class InputGatedMixin:
    """Base for an input-gated view: ensures `request.organization` (via `ensure_organization`) and
    attaches the organization's `InputState` as `request.input_state`, computed once per request.
    Inherit this instead of decorating dispatch with `ensure_organization` directly."""

    @method_decorator( ensure_organization )
    def dispatch( self, request, *args, **kwargs ):
        request.input_state = input_state( request.organization )
        return super().dispatch( request, *args, **kwargs )
