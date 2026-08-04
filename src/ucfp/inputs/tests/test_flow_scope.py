"""Entering a standalone flow clears a stale scenario-build scope.

The scenario build (ScenarioEditView) sets session `scenario_building` so the Plans flow chains into
Assumptions; it is cleared on build completion. An abandoned build leaves it set, which would make a
later standalone Plans edit wrongly chain into Assumptions. FlowEntryView -- the standalone entry, which
the scenario build never routes through -- clears it on entry.
"""
from django.test import RequestFactory, TestCase

from ucfp.inputs.views import FlowEntryView
from ucfp.session_state import SessionState


class FlowEntryScopeTests( TestCase ):

    def test_standalone_plans_entry_clears_stale_build_scope( self ):
        request = RequestFactory().get( '/inputs/plans/' )
        request.session       = dict()
        request.session_state = SessionState( scenario_building = 'stale-build-uuid' )
        FlowEntryView( flow = 'plans' ).get( request )
        self.assertIsNone( request.session_state.scenario_building )
