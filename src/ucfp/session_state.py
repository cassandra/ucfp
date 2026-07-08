from dataclasses import dataclass
from typing import Optional

from django.http import HttpRequest

from ucfp.accounts.books_table import BooksTableDefinition


@dataclass
class SessionState:
    """
    Typed encapsulation of the app's session-stored state.

    Django's session is a loosely-typed key/value store. This class is the
    single, well-typed view over it: each piece of per-user, cross-request
    state is a declared field, parsed (and coerced/validated) from the session
    in ``from_session()`` and written back in ``to_session()``. Views and
    templates read ``request.session_state`` -- attached to every request by
    ``SessionStateMiddleware`` (see ucfp/middleware.py) -- instead of poking at
    ``request.session`` directly, so every key's shape and default lives here.

    It starts empty; add state as the project needs it. The pattern per field:

        1. Declare a typed field with a default on the dataclass:
               example_id : int = None

        2. Parse + coerce it in ``from_session()`` (always with a safe fallback):
               try:
                   example_id = int( request.session.get('example_id') )
               except ( TypeError, ValueError ):
                   example_id = None
               return SessionState( example_id = example_id )

        3. Serialize it back in ``to_session()``:
               request.session['example_id'] = self.example_id

    Values that must also be visible to JavaScript belong in ClientConfig /
    AppConst (see ucfp/environment), not read from the session client-side.
    """

    # The active organization for the request, by uuid (resolved/persisted by the
    # `ensure_organization` view decorator). String form, since the session is JSON-backed.
    current_organization_uuid : Optional[ str ] = None

    # The plans and assumptions the user is currently working on, by uuid -- the inputs pages select
    # them (many of each coexist per organization, unlike the single latest profile). These are the
    # editing target for the flows and the default selection for a forecast run.
    current_plans_uuid : Optional[ str ] = None
    current_assumptions_uuid : Optional[ str ] = None

    # The user's BooksTable column lens (a results-view preference): the ordered visible columns,
    # carried across runs and adapted to each run's books on read. The definition owns its own
    # session storage form (see BooksTableDefinition.to_storage / from_storage).
    books_table_definition : Optional[ BooksTableDefinition ] = None

    def to_session( self, request : HttpRequest ):
        """Write this state back into the session (extend as fields are added)."""
        if not hasattr( request, 'session' ):
            return
        request.session[ 'current_organization_uuid' ] = self.current_organization_uuid
        request.session[ 'current_plans_uuid' ] = self.current_plans_uuid
        request.session[ 'current_assumptions_uuid' ] = self.current_assumptions_uuid
        request.session[ 'books_table_definition' ] = (
            None if self.books_table_definition is None else self.books_table_definition.to_storage() )
        return

    @staticmethod
    def from_session( request : HttpRequest ) -> 'SessionState':
        """Build a SessionState from the request's session, with safe defaults."""
        if not request or not hasattr( request, 'session' ):
            return SessionState()
        return SessionState(
            current_organization_uuid = request.session.get( 'current_organization_uuid' ),
            current_plans_uuid = request.session.get( 'current_plans_uuid' ),
            current_assumptions_uuid = request.session.get( 'current_assumptions_uuid' ),
            books_table_definition = BooksTableDefinition.from_storage(
                request.session.get( 'books_table_definition' ) ) )
