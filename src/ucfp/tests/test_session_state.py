"""Tests for SessionState's per-organization scoped context and its global preferences."""
from django.test import SimpleTestCase

from ucfp.session_state import OrganizationSessionContext, SessionState


class _FakeRequest:
    """A stand-in carrying just the `session` dict that to_session/from_session touch."""

    def __init__( self, session ):
        self.session = session


class PerOrganizationContextTests( SimpleTestCase ):

    def test_scoped_selection_is_kept_per_organization_across_switches( self ):
        state = SessionState( current_organization_uuid = 'org-a' )
        state.current_scenario_uuid = 'scenario-a'

        state.set_current_organization( 'org-b' )
        # A never-visited organization starts with a clean slate.
        self.assertIsNone( state.current_scenario_uuid )
        state.current_scenario_uuid = 'scenario-b'

        # Switching back restores org A's selection; org B's is retained in parallel.
        state.set_current_organization( 'org-a' )
        self.assertEqual( state.current_scenario_uuid, 'scenario-a' )
        state.set_current_organization( 'org-b' )
        self.assertEqual( state.current_scenario_uuid, 'scenario-b' )

    def test_scoped_write_without_a_current_organization_is_dropped( self ):
        state = SessionState()                      # no current organization
        state.current_plans_uuid = 'x'
        self.assertIsNone( state.current_plans_uuid )
        self.assertEqual( state.organization_contexts, {} )

    def test_global_preferences_are_shared_across_organizations( self ):
        state = SessionState( current_organization_uuid = 'org-a' )
        state.forecast_interval = 'annual'
        state.set_current_organization( 'org-b' )
        self.assertEqual( state.forecast_interval, 'annual' )

    def test_round_trips_per_organization_context_through_the_session( self ):
        state = SessionState( current_organization_uuid = 'org-a' )
        state.current_plans_uuid = 'plans-a'
        state.editing_scenario   = 'build-a'
        state.set_current_organization( 'org-b' )
        state.current_plans_uuid = 'plans-b'

        request = _FakeRequest( dict() )
        state.to_session( request )
        restored = SessionState.from_session( request )

        self.assertEqual( restored.current_organization_uuid, 'org-b' )
        self.assertEqual( restored.current_plans_uuid, 'plans-b' )
        restored.set_current_organization( 'org-a' )
        self.assertEqual( restored.current_plans_uuid, 'plans-a' )
        self.assertEqual( restored.editing_scenario, 'build-a' )


class OrganizationSessionContextTests( SimpleTestCase ):

    def test_from_storage_ignores_unknown_keys_and_defaults_missing( self ):
        context = OrganizationSessionContext.from_storage(
            { 'current_plans_uuid': 'p', 'unexpected': 1 } )
        self.assertEqual( context.current_plans_uuid, 'p' )
        self.assertIsNone( context.current_scenario_uuid )

    def test_from_storage_tolerates_none( self ):
        self.assertEqual(
            OrganizationSessionContext.from_storage( None ), OrganizationSessionContext() )
