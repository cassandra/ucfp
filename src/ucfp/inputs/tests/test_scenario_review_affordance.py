"""The Scenarios home as a scenario review hub.

`ScenarioEditView` is the single op behind the full walk (Plans -> Assumptions) and has never guarded on
completeness, but the home template used to render its trigger only for in-progress scenarios -- so a
finished scenario offered no way back into the whole flow. The home now renders that trigger for every
scenario, labelled by state ("Finish setup" / "Review scenario"), and frames each scenario as a hero card
whose Plans and Assumptions are nested parts (each with a quiet Edit), with the component library demoted
behind a "Manage components" toggle.
"""
from datetime import date

from django.test import RequestFactory, TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.interview import applicable_sections, first_section_of_flow, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.views import ScenarioEditView, ScenariosHomeView
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.session_state import SessionState


def _acknowledge_flow( record, profile, flow ):
    """Mark `record` as having walked every applicable, live section of `flow` -- the completeness the
    home reads. Mirrors what reviewing the flow does, without walking it."""
    record.acknowledged_sections = [
        section.key for section in applicable_sections( profile )
        if flow_of( section ) == flow and section.form is not None ]
    record.save( update_fields = [ 'acknowledged_sections' ] )


class _ScenariosHomeTestBase( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()
        # A complete profile is the home's gate; without it the page shows the profile-required pane.
        self.profile = Profile(
            subjects = [ SubjectProfile( handle = 'subject', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE )
        save_profile( self.organization, self.profile )
        _acknowledge_flow( latest_profile( self.organization ), self.profile, 'profile' )

    def _scenario( self, *, complete, label ):
        """A saved scenario over fresh, empty Plans and Assumptions records (built directly to avoid the
        externally-seeded default economics); `complete` acknowledges both flows so the home ranks it
        finished."""
        plans       = PlansRecord( organization = self.organization, label = f'{label} Plans' )
        assumptions = AssumptionsRecord( organization = self.organization, label = f'{label} Assumptions' )
        save_plans( plans, Plans() )
        save_assumptions( assumptions, Assumptions() )
        if complete:
            _acknowledge_flow( plans, self.profile, 'plans' )
            _acknowledge_flow( assumptions, self.profile, 'assumptions' )
        return create_scenario( self.organization, plans, assumptions, label = label )

    def _home_content( self ):
        request = self.factory.get( '/inputs/scenarios/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return ScenariosHomeView().get( request ).content.decode()


class ScenarioReviewAffordanceTests( _ScenariosHomeTestBase ):

    def test_scenario_edit_enters_the_full_flow_for_a_complete_scenario( self ):
        scenario = self._scenario( complete = True, label = 'Done' )
        request  = self.factory.get( '/inputs/scenarios/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()

        response = ScenarioEditView().post( request, uuid = scenario.uuid )

        self.assertEqual( request.session_state.editing_scenario, str( scenario.uuid ) )
        self.assertRedirects(
            response,
            reverse( 'interview_section', kwargs = { 'section': first_section_of_flow( 'plans' ).key } ),
            fetch_redirect_response = False )

    def test_home_labels_review_on_complete_and_finish_on_incomplete( self ):
        done = self._scenario( complete = True, label = 'Done' )
        half = self._scenario( complete = False, label = 'Half-built' )

        content = self._home_content()

        self.assertIn( 'Review scenario', content )                 # the complete one is now re-enterable
        self.assertIn( 'Finish setup', content )                    # the in-progress one keeps its label
        # Both labels drive the same op, so both scenario rows post to their scenario_edit.
        self.assertIn( reverse( 'scenario_edit', args = [ done.uuid ] ), content )
        self.assertIn( reverse( 'scenario_edit', args = [ half.uuid ] ), content )

    def test_home_omits_review_when_no_scenario_is_complete( self ):
        self._scenario( complete = False, label = 'Half-built' )

        content = self._home_content()

        self.assertNotIn( 'Review scenario', content )
        self.assertIn( 'Finish setup', content )


class ScenarioHeroLayoutTests( _ScenariosHomeTestBase ):

    def test_scenario_shows_its_parts_with_edit_links_and_inline_rename( self ):
        scenario = self._scenario( complete = True, label = 'Done' )

        content = self._home_content()

        # The scenario's own Plans and Assumptions are nested parts, each reachable via its edit flow.
        self.assertIn( reverse( 'plans_edit', args = [ scenario.plans.uuid ] ), content )
        self.assertIn( reverse( 'assumptions_edit', args = [ scenario.assumptions.uuid ] ), content )
        # The scenario name is inline-renamable (the parts are not).
        self.assertIn( reverse( 'scenario_rename', args = [ scenario.uuid ] ), content )

    def test_component_library_is_tucked_behind_the_manage_collapse( self ):
        self._scenario( complete = True, label = 'Done' )

        content = self._home_content()

        # The library still exists, but only inside the collapsed "manage" region, named for the user
        # (not the internal "components").
        self.assertIn( 'Manage individual Plans and Assumptions', content )
        self.assertIn( 'id="manage-components"', content )
        self.assertIn( 'class="collapse"', content )
        self.assertIn( '+ New plan', content )

    def test_new_scenario_creation_is_present_but_demoted( self ):
        self._scenario( complete = True, label = 'Done' )

        content = self._home_content()

        self.assertIn( '+ New scenario', content )
        self.assertIn( reverse( 'scenario_compose' ), content )

    def test_delete_hidden_for_a_component_whose_removal_would_orphan_scenarios( self ):
        scenario = self._scenario( complete = True, label = 'Only' )
        spare    = PlansRecord( organization = self.organization, label = 'Spare Plans' )
        save_plans( spare, Plans() )                            # a second set: the per-kind guard alone allows delete

        content = self._home_content()

        # The scenario's own Plans still can't be deleted (its cascade would leave no scenario)...
        self.assertNotIn( reverse( 'plans_delete', args = [ scenario.plans.uuid ] ), content )
        # ...but the unused spare can.
        self.assertIn( reverse( 'plans_delete', args = [ spare.uuid ] ), content )

    def test_the_only_scenario_offers_no_delete( self ):
        scenario = self._scenario( complete = True, label = 'Only' )

        content = self._home_content()

        # A household keeps at least one scenario, so the sole scenario's delete control is suppressed.
        self.assertNotIn( 'Delete scenario', content )
        self.assertNotIn( reverse( 'scenario_delete', args = [ scenario.uuid ] ), content )

    def test_delete_appears_once_a_second_scenario_exists( self ):
        self._scenario( complete = True, label = 'One' )
        self._scenario( complete = True, label = 'Two' )

        content = self._home_content()

        self.assertIn( 'Delete scenario', content )


class ScenarioMultiplicityTests( _ScenariosHomeTestBase ):
    """With more than one scenario, a component backing several shows a "shared" indicator, and the
    component library is surfaced (shown) rather than tucked behind the toggle."""

    def _component( self, model, label ):
        record = model( organization = self.organization, label = label )
        ( save_plans if model is PlansRecord else save_assumptions )(
            record, Plans() if model is PlansRecord else Assumptions() )
        return record

    def test_a_component_backing_several_scenarios_shows_a_shared_indicator( self ):
        shared_plans = self._component( PlansRecord, 'Shared Plans' )
        create_scenario( self.organization, shared_plans, self._component( AssumptionsRecord, 'A1' ), 'S1' )
        create_scenario( self.organization, shared_plans, self._component( AssumptionsRecord, 'A2' ), 'S2' )

        content = self._home_content()

        self.assertIn( '>Shared</span>', content )

    def test_a_singly_used_component_shows_no_shared_indicator( self ):
        self._scenario( complete = True, label = 'Solo' )       # its own Plans and Assumptions, used once

        content = self._home_content()

        self.assertNotIn( '>Shared</span>', content )

    def test_library_is_surfaced_open_with_multiple_scenarios( self ):
        self._scenario( complete = True, label = 'One' )
        self._scenario( complete = True, label = 'Two' )

        self.assertIn( 'class="collapse show"', self._home_content() )

    def test_library_stays_collapsed_with_a_single_scenario( self ):
        self._scenario( complete = True, label = 'Only' )

        content = self._home_content()

        self.assertIn( 'id="manage-components"', content )
        self.assertNotIn( 'class="collapse show"', content )
