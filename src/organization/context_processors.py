"""Template context processors for the organization app."""
from ucfp.accounts.enums import CurrencyType


def current_currency( request ):
    """Expose the active organization's display currency to every template as ``currency`` -- the
    argument the ``money`` filter takes. Falls back to the default when no organization is resolved
    on the request (e.g. public pages), so templates can format money unconditionally.

    The organization is attached by the ``ensure_organization`` view decorator; this reads it
    defensively so the processor is safe on requests that never set it."""
    organization = getattr( request, 'organization', None )
    currency = organization.currency if organization is not None else CurrencyType.default()
    return { 'currency': currency }
