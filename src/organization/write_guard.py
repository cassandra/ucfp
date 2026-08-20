"""A fail-safe backstop that blocks organization-data writes during a read-only member's request.

The HTTP-method write-gate (`decorators.ensure_organization`) refuses a read-only member's unsafe-method
requests, but some data writes ride a GET -- e.g. an interview marking a section acknowledged on view.
Those are meant to be skipped for a read-only member at the source (a graceful no-op, so viewing still
works); this backstop guarantees that a write the method-gate cannot see, and that a source guard misses,
**fails toward denied** rather than silently changing shared data.

Mechanism: the request path runs a read-only member's view inside `writes_permitted(False)`, and each
guarded model (registered by its app via `connect_write_guard`) refuses to persist while writes are not
permitted. It is a backstop, not the primary control -- the method-gate and the source guards are; this
catches the gaps.
"""
import contextvars
from contextlib import contextmanager

from django.core.exceptions import PermissionDenied
from django.db.models.signals import pre_delete, pre_save

# Per-request (context-local) permission to persist guarded models. Defaults to True, so any code path
# not wrapped by `writes_permitted` (management commands, writers' requests) persists normally.
_writes_permitted = contextvars.ContextVar( 'organization_writes_permitted', default = True )


@contextmanager
def writes_permitted( permitted ):
    """Run the body with guarded-model writes permitted or not, per `permitted`.

    The request path passes the member's write capability, so a read-only member's view runs with writes
    refused -- any organization-data write the method-gate could not see is blocked. Restores the previous
    value on exit, so it nests and never leaks to the next request sharing the thread.
    """
    token = _writes_permitted.set( bool( permitted ) )
    try:
        yield
    finally:
        _writes_permitted.reset( token )


def _refuse_forbidden_write( sender, **kwargs ):
    if not _writes_permitted.get():
        raise PermissionDenied(
            f'This household is read-only for your role; a write to {sender.__name__} was blocked.' )


def connect_write_guard( *models ):
    """Guard each model's persistence against a read-only member's request -- the fail-safe backstop
    behind the method write-gate. An app registers its organization-scoped record models from its
    `signals` module. Idempotent per model (stable `dispatch_uid`)."""
    for model in models:
        uid = f'organization.write_guard:{model.__module__}.{model.__name__}'
        pre_save.connect( _refuse_forbidden_write, sender = model, dispatch_uid = f'{uid}:save' )
        pre_delete.connect( _refuse_forbidden_write, sender = model, dispatch_uid = f'{uid}:delete' )
