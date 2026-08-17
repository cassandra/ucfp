"""The Scenarios home as a scenario review hub.

`ScenarioEditView` is the single op behind the full walk (Plans -> Assumptions) and has never guarded on
completeness, but the home template used to render its trigger only for in-progress scenarios -- so a
finished scenario offered no way back into the whole flow. The home now renders that trigger for every
scenario, labelled by state ("Finish setup" / "Review scenario"), and frames each scenario as a hero card
whose Plans and Assumptions are nested parts (each with a quiet Edit), with the component library demoted
behind a "Manage components" toggle.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.interview import applicable_sections, first_section_of_flow, flow_of
from ucfp.jurisdiction.enums import StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.profile.schemas import Debt, Profile, SubjectProfile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.inputs.views import InterviewView, ScenarioEditView, ScenariosHomeView
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.session_state import SessionState


def _complete_assumptions() -> Assumptions:
    """A valid Assumptions (economic outlook + tax projection present) so an acknowledged one is complete --
    the external factors are a completeness requirement now. Built directly, no parameter-set seed needed."""
    return Assumptions(
        economics = EconomicParameters(),
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


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
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )
        save_profile( self.organization, self.profile )
        _acknowledge_flow( latest_profile( self.organization ), self.profile, 'profile' )

    def _scenario( self, *, complete, label ):
        """A saved scenario over fresh, empty Plans and Assumptions records (built directly to avoid the
        externally-seeded default economics); `complete` acknowledges both flows so the home ranks it
        finished."""
        plans       = PlansRecord( organization = self.organization, label = f'{label} Plans' )
        assumptions = AssumptionsRecord( organization = self.organization, label = f'{label} Assumptions' )
        save_plans( plans, Plans() )
        save_assumptions( assumptions, _complete_assumptions() )
        if complete:
            _acknowledge_flow( plans, self.profile, 'plans' )
            _acknowledge_flow( assumptions, self.profile, 'assumptions' )
        return create_scenario( self.organization, plans, assumptions, label = label )

    def _keep_list_visible( self ):
        """A second, throwaway scenario (its own distinct components) so the home renders its card list
        rather than taking the single-scenario shortcut, which redirects straight into the sole scenario's
        edit flow. Left in-progress so it never adds a 'Review' affordance or a 'shared' indicator."""
        return self._scenario( complete = False, label = 'Filler' )

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

    def test_a_sole_scenario_is_entered_directly( self ):
        scenario = self._scenario( complete = True, label = 'Only' )
        request  = self.factory.get( '/inputs/scenarios/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()

        response = ScenariosHomeView().get( request )

        # One scenario: skip the one-card list and drop straight into its edit flow (as its card CTA would).
        self.assertEqual( response.status_code, 302 )
        self.assertEqual(
            response.url,
            reverse( 'interview_section', kwargs = { 'section': first_section_of_flow( 'plans' ).key } ) )
        self.assertEqual( request.session_state.editing_scenario, str( scenario.uuid ) )

    def test_home_omits_review_when_no_scenario_is_complete( self ):
        self._scenario( complete = False, label = 'Half-built' )
        self._keep_list_visible()                                   # a 2nd scenario keeps the list on-screen

        content = self._home_content()

        self.assertNotIn( 'Review scenario', content )
        self.assertIn( 'Finish setup', content )

    def test_a_finished_but_blocked_scenario_reads_incomplete_with_its_reason( self ):
        # A debt in the profile, a scenario whose Plans is fully walked but sets no repayment -- finished
        # but blocked (State 1), which must read as danger with the reason, not the neutral "Finish setup".
        profile = replace( self.profile, debts = [ Debt(
            handle = 'loan', name = 'Mortgage', kind = DebtKind.MORTGAGE, balance = Decimal( '100000' ) ) ] )
        save_profile( self.organization, profile )
        _acknowledge_flow( latest_profile( self.organization ), profile, 'profile' )
        plans       = PlansRecord( organization = self.organization, label = 'Blocked Plans' )
        assumptions = AssumptionsRecord( organization = self.organization, label = 'Blocked Assumptions' )
        save_plans( plans, Plans() )                       # every plans step walked, but no repayment
        save_assumptions( assumptions, _complete_assumptions() )
        _acknowledge_flow( plans, profile, 'plans' )
        _acknowledge_flow( assumptions, profile, 'assumptions' )
        create_scenario( self.organization, plans, assumptions, label = 'Blocked' )
        self._keep_list_visible()                                  # a 2nd scenario keeps the list on-screen

        content = self._home_content()

        self.assertIn( 'badge-danger', content )                          # State 1, not the grey in-progress
        self.assertIn( "This scenario can't run yet", content )
        self.assertIn( 'Set a repayment plan for the Mortgage.', content )
        # Both unfinished states share the action; the danger badge + alert (asserted above) are the tell.
        self.assertIn( 'Finish setup', content )


class ScenarioHeroLayoutTests( _ScenariosHomeTestBase ):

    def test_scenario_shows_its_parts_with_review_links( self ):
        scenario = self._scenario( complete = True, label = 'Done' )
        self._keep_list_visible()                                  # a 2nd scenario keeps the list on-screen

        content = self._home_content()

        # The scenario's own Plans and Assumptions are nested parts, each reachable via its review flow.
        self.assertIn( reverse( 'plans_edit', args = [ scenario.plans.uuid ] ), content )
        self.assertIn( reverse( 'assumptions_edit', args = [ scenario.assumptions.uuid ] ), content )
        # The name is plain text here, not an inline rename -- it is renamed on the interview page, like the
        # parts (which are not renamed on the card either).
        self.assertNotIn( reverse( 'scenario_rename', args = [ scenario.uuid ] ), content )

    def test_new_scenario_creation_is_present( self ):
        self._scenario( complete = True, label = 'Done' )
        self._keep_list_visible()                                  # a 2nd scenario keeps the list on-screen

        content = self._home_content()

        self.assertIn( '+ New scenario', content )
        self.assertIn( reverse( 'scenario_compose' ), content )

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
            record, Plans() if model is PlansRecord else _complete_assumptions() )
        return record

    def test_a_component_backing_several_scenarios_shows_a_shared_indicator( self ):
        shared_plans = self._component( PlansRecord, 'Shared Plans' )
        create_scenario( self.organization, shared_plans, self._component( AssumptionsRecord, 'A1' ), 'S1' )
        create_scenario( self.organization, shared_plans, self._component( AssumptionsRecord, 'A2' ), 'S2' )

        content = self._home_content()

        # The badge is attributed to the shared Plans, not the distinct Assumptions -- catches the
        # plans_uses / assumptions_uses counters being swapped (both cases would leave a bare "Shared" in
        # the page, so a plain substring check would not).
        self.assertRegex( content, r'Shared Plans\s*<span[^>]*>Shared</span>' )
        self.assertNotRegex( content, r'>A[12]\s*<span[^>]*>Shared</span>' )

    def test_a_singly_used_component_shows_no_shared_indicator( self ):
        self._scenario( complete = True, label = 'Solo' )       # its own Plans and Assumptions, used once
        self._keep_list_visible()                               # a 2nd (distinct) scenario keeps the list up

        content = self._home_content()

        self.assertNotIn( '>Shared</span>', content )


class RailHeaderContextTests( _ScenariosHomeTestBase ):
    """InterviewView._rail_header: the stepper's part switch. In a scenario build it lists both parts (the
    active one flagged, each with its own completion status, the other linking to its first section);
    editing a component on its own, just that one part with no switch."""

    def _request( self, scenario, *, building ):
        request = self.factory.get( '/inputs/interview/x/' )
        request.organization  = self.organization
        request.session       = dict()
        request.session_state = SessionState(
            current_plans_uuid       = str( scenario.plans.uuid ),
            current_assumptions_uuid = str( scenario.assumptions.uuid ),
            editing_scenario         = str( scenario.uuid ) if building else None )
        return request

    def test_a_scenario_build_shows_both_parts_with_the_active_one_flagged( self ):
        scenario = self._scenario( complete = True, label = 'Done' )

        header = InterviewView()._rail_header( self._request( scenario, building = True ), 'plans' )

        self.assertTrue( header[ 'rail_scenario_mode' ] )
        self.assertEqual( [ part[ 'label' ] for part in header[ 'rail_parts' ] ], [ 'Plans', 'Assumptions' ] )
        self.assertEqual( [ part[ 'label' ] for part in header[ 'rail_parts' ] if part[ 'active' ] ],
                          [ 'Plans' ] )
        # Both components are walked and clean, so each part reads complete.
        self.assertEqual( [ part[ 'status' ] for part in header[ 'rail_parts' ] ], [ 'complete', 'complete' ] )

    def test_the_inactive_part_links_to_its_first_section( self ):
        scenario = self._scenario( complete = True, label = 'Done' )

        header      = InterviewView()._rail_header( self._request( scenario, building = True ), 'plans' )
        assumptions = next( part for part in header[ 'rail_parts' ] if part[ 'label' ] == 'Assumptions' )

        self.assertEqual(
            assumptions[ 'url' ],
            reverse( 'interview_section',
                     kwargs = { 'section': first_section_of_flow( 'assumptions' ).key } ) )

    def test_an_individual_component_edit_shows_a_single_part_and_no_switch( self ):
        scenario = self._scenario( complete = False, label = 'Solo' )

        header = InterviewView()._rail_header( self._request( scenario, building = False ), 'plans' )

        self.assertFalse( header[ 'rail_scenario_mode' ] )
        self.assertEqual( [ part[ 'label' ] for part in header[ 'rail_parts' ] ], [ 'Plans' ] )
        self.assertEqual( header[ 'rail_parts' ][ 0 ][ 'status' ], 'in_progress' )   # not walked yet
