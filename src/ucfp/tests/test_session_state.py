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


class ChartInflationPreferenceTests( SimpleTestCase ):
    """The global `adjust_charts_for_inflation` preference: default-on, and its round-trip. The default is a
    back-compat contract -- sessions written before the field existed lack the key and must read as True, so
    an existing user's charts stay on the today's-dollars basis rather than silently flipping to nominal."""

    def test_a_session_missing_the_key_defaults_to_adjusting_for_inflation( self ):
        # A pre-existing session (no such key) -- from_session must supply the on-by-default.
        restored = SessionState.from_session( _FakeRequest( dict() ) )
        self.assertTrue( restored.adjust_charts_for_inflation )

    def test_the_preference_round_trips_when_turned_off( self ):
        state = SessionState( adjust_charts_for_inflation = False )
        request = _FakeRequest( dict() )
        state.to_session( request )
        self.assertFalse( SessionState.from_session( request ).adjust_charts_for_inflation )


class OrganizationSessionContextTests( SimpleTestCase ):

    def test_from_storage_ignores_unknown_keys_and_defaults_missing( self ):
        context = OrganizationSessionContext.from_storage(
            { 'current_plans_uuid': 'p', 'unexpected': 1 } )
        self.assertEqual( context.current_plans_uuid, 'p' )
        self.assertIsNone( context.current_scenario_uuid )

    def test_from_storage_tolerates_none( self ):
        self.assertEqual(
            OrganizationSessionContext.from_storage( None ), OrganizationSessionContext() )
