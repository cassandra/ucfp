from dataclasses import dataclass, field
from typing import Optional

from django.http import HttpRequest

from ucfp.accounts.books_table import BooksTableDefinition
from ucfp.session_facts import SessionFacts


def _int_or_none( value ) -> Optional[ int ]:
    """A stored value coerced to int, or None when absent or malformed -- the safe read for an
    integer session field (the session is JSON-backed, but tolerate a bad value rather than raise)."""
    try:
        return int( value )
    except ( TypeError, ValueError ):
        return None


@dataclass
class OrganizationSessionContext:
    """The session selections scoped to a single organization.

    These are the choices that only make sense against one organization's data: the plans/assumptions
    being edited, the scenario last run, an in-progress build, and the Explore curation. They are held
    per organization (in ``SessionState.organization_contexts``, keyed by organization uuid) so moving
    between organizations preserves each one's place instead of resetting it. Callers never touch this
    class directly -- ``SessionState`` surfaces the *current* organization's slot through flat
    properties (``current_plans_uuid`` and friends), so switching organizations is just re-pointing
    ``current_organization_uuid``.
    """

    # The plans and assumptions the user is currently working on, by uuid -- the inputs pages select
    # them (many of each coexist per organization, unlike the single latest profile). These are the
    # editing target for the flows.
    current_plans_uuid       : Optional[ str ]  = None
    current_assumptions_uuid : Optional[ str ]  = None

    # The saved scenario the user last ran or explored, by uuid -- the hub's scenario chooser defaults to
    # it rather than the most-recent one. A stale value (scenario deleted) simply does not preselect.
    current_scenario_uuid    : Optional[ str ]  = None

    # The scenario currently being built, by uuid -- set while the Plans->Assumptions build flow runs, so
    # the interview chains the two component flows and finalizes on completion. Cleared when the build
    # finishes; None means no build is in progress.
    editing_scenario         : Optional[ str ]  = None

    # Which inputs each Explore section keeps visible when collapsed (the curated subset) -- a per-section
    # list of handles. A visual convenience only; None means "not yet curated", so the section falls back
    # to its built-in default selection.
    explore_curated_expenses : Optional[ list ] = None
    explore_curated_rates    : Optional[ list ] = None

    _STORAGE_FIELDS = (
        'current_plans_uuid',
        'current_assumptions_uuid',
        'current_scenario_uuid',
        'editing_scenario',
        'explore_curated_expenses',
        'explore_curated_rates',
    )

    def to_storage( self ) -> dict:
        """This slot as a JSON-serializable dict for the session."""
        return { name: getattr( self, name ) for name in self._STORAGE_FIELDS }

    @staticmethod
    def from_storage( raw ) -> 'OrganizationSessionContext':
        """Rebuild a slot from its stored dict, tolerating missing or unexpected keys."""
        raw = raw or {}
        return OrganizationSessionContext(
            **{ name: raw.get( name ) for name in OrganizationSessionContext._STORAGE_FIELDS } )


@dataclass
class SessionState:
    """
    Typed encapsulation of the app's session-stored state.

    Django's session is a loosely-typed key/value store. This class is the single, well-typed view over
    it: each piece of per-user, cross-request state is a declared field, parsed (and coerced/validated)
    from the session in ``from_session()`` and written back in ``to_session()``. Views and templates read
    ``request.session_state`` -- attached to every request by ``SessionStateMiddleware`` (see
    ucfp/middleware.py) -- instead of poking at ``request.session`` directly, so every key's shape and
    default lives here.

    State comes in two kinds:

      - **Organization-scoped** selections (scenario, plans/assumptions, in-progress build, Explore
        curation) live in ``organization_contexts``, one ``OrganizationSessionContext`` per organization
        uuid, and are surfaced for the *current* organization through flat properties
        (``current_plans_uuid`` and friends). This keeps each organization's place across switches while
        callers keep using one flat interface.
      - **Global** preferences (the run frame, the books-table lens, cookie consent) are plain fields,
        shared across organizations.

    Values that must also be visible to JavaScript belong in ClientConfig / AppConst (see
    ucfp/environment), not read from the session client-side.
    """

    # The active organization for the request, by uuid (resolved/persisted by the `ensure_organization`
    # view decorator). String form, since the session is JSON-backed. Re-pointing this (see
    # `set_current_organization`) is the whole of switching organizations.
    current_organization_uuid : Optional[ str ] = None

    # Per-organization scoped selections, keyed by organization uuid. Surfaced for the current
    # organization through the properties below; not accessed directly by callers.
    organization_contexts : dict = field( default_factory = dict )

    # The user's BooksTable column lens (a results-view preference): the ordered visible columns,
    # carried across runs and adapted to each run's books on read. The definition owns its own
    # session storage form (see BooksTableDefinition.to_storage / from_storage).
    books_table_definition : Optional[ BooksTableDefinition ] = None

    # The forecast run frame the user last chose on the hub (start-from choice, duration in years, and
    # interval), so the run form's when-controls default to that selection rather than its built-in
    # defaults. Stored raw (the ForecastForm re-validates on submit); a stale value simply does not preselect.
    forecast_start_from : Optional[ str ] = None
    forecast_duration_years : Optional[ int ] = None
    forecast_interval : Optional[ str ] = None

    # Whether the visitor has acknowledged the cookie-usage notice, so the banner is not
    # shown again this session (see ucfp.privacy_consent).
    cookies_acknowledged : bool = False

    # Feature-neutral household facts a visitor has entered into the login-free tools (birth years, benefit
    # amounts, an expected lifetime), so a tool can re-prefill them and a brand-new Profile can be seeded
    # from them. NOT org-scoped -- it works for an anonymous visitor with no organization. The neutral bag
    # and its Profile mapping live in ucfp.session_facts / the profile repository, not here.
    session_facts : SessionFacts = field( default_factory = SessionFacts )

    # The economic assumptions a visitor last ran the Social Security claiming calculator under (inflation,
    # the benefit reduction and its year), so a return visit re-prefills them. Feature-specific to that
    # calculator and kept as its raw form values -- the household facts it also collects live in
    # `session_facts` (see ucfp.calculators.ss_timing).
    ss_timing_assumptions : dict = field( default_factory = dict )

    def set_current_organization( self, organization_uuid : Optional[ str ] ) -> None:
        """Make `organization_uuid` the current organization.

        Because the scoped selections are held per organization and surfaced for whichever one is
        current, this restores the target organization's context automatically -- there is nothing to
        clear or copy. The single switch primitive, shared by the user-facing switch and any server-side
        reselection.
        """
        self.current_organization_uuid = organization_uuid
        return

    # -- current-organization scoped selections: proxied into the current org's slot ---------------

    def _current_context( self, create : bool = False ) -> Optional[ OrganizationSessionContext ]:
        key = self.current_organization_uuid
        if key is None:
            return None
        context = self.organization_contexts.get( key )
        if ( context is None ) and create:
            context = OrganizationSessionContext()
            self.organization_contexts[ key ] = context
        return context

    def _scoped_get( self, name : str ):
        context = self._current_context()
        return getattr( context, name ) if context is not None else None

    def _scoped_set( self, name : str, value ):
        # A write with no current organization has nowhere to belong; drop it rather than key a slot on
        # None. In a resolved request the organization is always set first, so this never bites.
        context = self._current_context( create = True )
        if context is not None:
            setattr( context, name, value )
        return

    @property
    def current_plans_uuid( self ) -> Optional[ str ]:
        return self._scoped_get( 'current_plans_uuid' )

    @current_plans_uuid.setter
    def current_plans_uuid( self, value ):
        self._scoped_set( 'current_plans_uuid', value )

    @property
    def current_assumptions_uuid( self ) -> Optional[ str ]:
        return self._scoped_get( 'current_assumptions_uuid' )

    @current_assumptions_uuid.setter
    def current_assumptions_uuid( self, value ):
        self._scoped_set( 'current_assumptions_uuid', value )

    @property
    def current_scenario_uuid( self ) -> Optional[ str ]:
        return self._scoped_get( 'current_scenario_uuid' )

    @current_scenario_uuid.setter
    def current_scenario_uuid( self, value ):
        self._scoped_set( 'current_scenario_uuid', value )

    @property
    def editing_scenario( self ) -> Optional[ str ]:
        return self._scoped_get( 'editing_scenario' )

    @editing_scenario.setter
    def editing_scenario( self, value ):
        self._scoped_set( 'editing_scenario', value )

    @property
    def explore_curated_expenses( self ) -> Optional[ list ]:
        return self._scoped_get( 'explore_curated_expenses' )

    @explore_curated_expenses.setter
    def explore_curated_expenses( self, value ):
        self._scoped_set( 'explore_curated_expenses', value )

    @property
    def explore_curated_rates( self ) -> Optional[ list ]:
        return self._scoped_get( 'explore_curated_rates' )

    @explore_curated_rates.setter
    def explore_curated_rates( self, value ):
        self._scoped_set( 'explore_curated_rates', value )

    def to_session( self, request : HttpRequest ):
        """Write this state back into the session (extend as fields are added)."""
        if not hasattr( request, 'session' ):
            return
        request.session[ 'current_organization_uuid' ] = self.current_organization_uuid
        request.session[ 'organization_contexts' ] = {
            key: context.to_storage() for key, context in self.organization_contexts.items() }
        request.session[ 'books_table_definition' ] = (
            None if self.books_table_definition is None else self.books_table_definition.to_storage() )
        request.session[ 'forecast_start_from' ] = self.forecast_start_from
        request.session[ 'forecast_duration_years' ] = self.forecast_duration_years
        request.session[ 'forecast_interval' ] = self.forecast_interval
        request.session[ 'cookies_acknowledged' ] = self.cookies_acknowledged
        request.session[ 'session_facts' ] = self.session_facts.to_storage()
        request.session[ 'ss_timing_assumptions' ] = self.ss_timing_assumptions
        return

    @staticmethod
    def from_session( request : HttpRequest ) -> 'SessionState':
        """Build a SessionState from the request's session, with safe defaults."""
        if not request or not hasattr( request, 'session' ):
            return SessionState()
        raw_contexts = request.session.get( 'organization_contexts' ) or {}
        organization_contexts = {
            key: OrganizationSessionContext.from_storage( values )
            for key, values in raw_contexts.items() }
        return SessionState(
            current_organization_uuid = request.session.get( 'current_organization_uuid' ),
            organization_contexts = organization_contexts,
            books_table_definition = BooksTableDefinition.from_storage(
                request.session.get( 'books_table_definition' ) ),
            forecast_start_from = request.session.get( 'forecast_start_from' ),
            forecast_duration_years = _int_or_none( request.session.get( 'forecast_duration_years' ) ),
            forecast_interval = request.session.get( 'forecast_interval' ),
            cookies_acknowledged = bool( request.session.get( 'cookies_acknowledged', False ) ),
            session_facts = SessionFacts.from_storage( request.session.get( 'session_facts' ) ),
            ss_timing_assumptions = request.session.get( 'ss_timing_assumptions' ) or {} )
