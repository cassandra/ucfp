"""Where the interview advances to, and the read-only Next/Finish that mirrors it.

`_following_section` is the single source of truth shared by the advance POST, the editable Finish/Next
label, and the read-only "Next": in a scenario build the last Plans step chains into Assumptions (a
"Next"), otherwise it finishes. `_completion_destination` is a *pure* URL -- the build is finalized in
`post()`, not on render -- so computing it while rendering never ends a build in progress.
"""
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from ucfp.inputs.interview import first_section_of_flow
from ucfp.inputs.views import InterviewView
from ucfp.session_state import SessionState


def _request( *, building ):
    request = RequestFactory().get( '/' )
    request.session = dict()
    state = SessionState( current_organization_uuid = 'org-uuid' )
    if building:
        state.editing_scenario = 'scenario-uuid'
    request.session_state = state
    return request


class FollowingSectionTest( SimpleTestCase ):

    def test_last_plans_step_chains_into_assumptions_in_a_build( self ):
        plans_last = first_section_of_flow( 'plans' )                 # a one-section list makes it the last
        following = InterviewView._following_section(
            _request( building = True ), [ plans_last ], plans_last.key, 'plans' )
        self.assertEqual( following, first_section_of_flow( 'assumptions' ) )

    def test_last_plans_step_finishes_when_editing_plans_alone( self ):
        plans_last = first_section_of_flow( 'plans' )
        following = InterviewView._following_section(
            _request( building = False ), [ plans_last ], plans_last.key, 'plans' )
        self.assertIsNone( following )


class CompletionDestinationPurityTest( SimpleTestCase ):

    def test_computing_the_destination_does_not_finalize_the_build( self ):
        request = _request( building = True )
        url = InterviewView._completion_destination( request, 'assumptions', building = True )
        self.assertEqual( url, reverse( 'scenarios_home' ) )
        # The build marker is untouched -- finalization belongs to the POST, not to rendering.
        self.assertEqual( request.session_state.editing_scenario, 'scenario-uuid' )
