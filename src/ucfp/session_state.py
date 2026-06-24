from dataclasses import dataclass
from typing import Optional

from django.http import HttpRequest


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

    # The scenario the user is currently working on, by uuid -- the scenario pages select it
    # (many scenarios coexist per organization, unlike the single latest profile).
    current_scenario_uuid : Optional[ str ] = None

    def to_session( self, request : HttpRequest ):
        """Write this state back into the session (extend as fields are added)."""
        if not hasattr( request, 'session' ):
            return
        request.session[ 'current_organization_uuid' ] = self.current_organization_uuid
        request.session[ 'current_scenario_uuid' ] = self.current_scenario_uuid
        return

    @staticmethod
    def from_session( request : HttpRequest ) -> 'SessionState':
        """Build a SessionState from the request's session, with safe defaults."""
        if not request or not hasattr( request, 'session' ):
            return SessionState()
        return SessionState(
            current_organization_uuid = request.session.get( 'current_organization_uuid' ),
            current_scenario_uuid = request.session.get( 'current_scenario_uuid' ) )
