"""The New scenario page (`ScenarioComposeView`): three creation paths, ranked by state.

Pair existing complete components into a not-yet-used combination, Copy an existing scenario (per side,
copy or reuse), or Start fresh (new default Plans + Assumptions, then the interview). Until a first
scenario is complete the page steers the user to finish that one. Completeness is set by acknowledging a
record's flow sections; components are built from empty schemas (the minting helpers pull seeded defaults).
"""
from datetime import date

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
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.inputs.scenarios.repository import create_scenario, scenarios_for
from ucfp.inputs.views import ScenarioComposeView
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.session_state import SessionState


def _acknowledge_flow( record, profile, flow ):
    record.acknowledged_sections = [
        section.key for section in applicable_sections( profile )
        if flow_of( section ) == flow and section.form is not None ]
    record.save( update_fields = [ 'acknowledged_sections' ] )


class _NewScenarioBase( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()
        self.profile = Profile(
            subjects = [ SubjectProfile( 'subject', 'You', date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )
        save_profile( self.organization, self.profile )
        _acknowledge_flow( latest_profile( self.organization ), self.profile, 'profile' )

    def _plans( self, label, complete = True ):
        record = PlansRecord( organization = self.organization, label = label )
        save_plans( record, Plans() )
        if complete:
            _acknowledge_flow( record, self.profile, 'plans' )
        return record

    def _assumptions( self, label, complete = True ):
        record = AssumptionsRecord( organization = self.organization, label = label )
        # Valid assumptions (outlook + tax present) so an acknowledged one is complete -- the external
        # factors are a completeness requirement now.
        save_assumptions( record, Assumptions(
            economics = EconomicParameters(),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) ) )
        if complete:
            _acknowledge_flow( record, self.profile, 'assumptions' )
        return record

    def _scenario( self, label, complete = True, plans = None, assumptions = None ):
        return create_scenario(
            self.organization, plans or self._plans( f'{label} P', complete ),
            assumptions or self._assumptions( f'{label} A', complete ), label )

    def _request( self, method, data = None ):
        request = getattr( self.factory, method )( '/inputs/scenarios/compose/', data or {} )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def _get( self ):
        return ScenarioComposeView().get( self._request( 'get' ) ).content.decode()


class NewScenarioStateTests( _NewScenarioBase ):

    def test_no_complete_scenario_steers_to_finishing_first( self ):
        self._scenario( 'Draft', complete = False )

        content = self._get()

        self.assertIn( 'Finish your current scenario first', content )
        self.assertNotIn( 'Copy a scenario', content )

    def test_a_complete_scenario_offers_copy_and_start_fresh( self ):
        self._scenario( 'Base', complete = True )

        content = self._get()

        self.assertIn( 'Copy a scenario', content )
        self.assertIn( 'Start fresh', content )

    def test_pair_is_offered_only_when_a_free_combination_exists( self ):
        plans, assumptions = self._plans( 'P1' ), self._assumptions( 'A1' )
        self._scenario( 'S1', plans = plans, assumptions = assumptions )   # only pairing so far
        self.assertNotIn( 'Pair existing components', self._get() )

        self._plans( 'P2' )                                                # a spare set -> (P2, A1) is free
        self.assertIn( 'Pair existing components', self._get() )


class NewScenarioCopyTests( _NewScenarioBase ):

    def _copy( self, **fields ):
        data = { 'action': 'copy' }
        data.update( { f'copy-{key}': value for key, value in fields.items() } )
        return ScenarioComposeView().post( self._request( 'post', data ) )

    def test_copy_both_creates_an_independent_scenario_and_redirects( self ):
        source = self._scenario( 'Base' )

        response = self._copy( source = str( source.uuid ), plans_mode = 'copy',
                               assumptions_mode = 'copy', name = 'Copy' )

        self.assertEqual( response.status_code, 302 )
        new = scenarios_for( self.organization ).get( label = 'Copy' )
        self.assertNotEqual( new.plans_id, source.plans_id )
        self.assertNotEqual( new.assumptions_id, source.assumptions_id )

    def test_reuse_one_side_shares_that_component( self ):
        source = self._scenario( 'Base' )

        self._copy( source = str( source.uuid ), plans_mode = 'reuse',
                    assumptions_mode = 'copy', name = 'Vary' )

        new = scenarios_for( self.organization ).get( label = 'Vary' )
        self.assertEqual( new.plans_id, source.plans_id )                  # shared
        self.assertNotEqual( new.assumptions_id, source.assumptions_id )   # cloned

    def test_reusing_both_sides_is_rejected( self ):
        source = self._scenario( 'Base' )

        response = self._copy( source = str( source.uuid ), plans_mode = 'reuse',
                               assumptions_mode = 'reuse', name = 'Dup' )

        self.assertEqual( response.status_code, 200 )                      # re-renders with the error
        self.assertFalse( scenarios_for( self.organization ).filter( label = 'Dup' ).exists() )

    def test_copy_rejects_a_duplicate_name( self ):
        source = self._scenario( 'Base' )                                  # 'Base' is now a taken name

        response = self._copy( source = str( source.uuid ), plans_mode = 'copy',
                               assumptions_mode = 'copy', name = 'Base' )

        self.assertEqual( response.status_code, 200 )
        self.assertEqual( scenarios_for( self.organization ).filter( label = 'Base' ).count(), 1 )

    def test_copy_from_an_incomplete_scenario_is_rejected( self ):
        self._scenario( 'Complete' )                                       # so the page is past state 0
        draft = self._scenario( 'Draft', complete = False )                # not a valid copy source

        response = self._copy( source = str( draft.uuid ), plans_mode = 'copy',
                               assumptions_mode = 'copy', name = 'FromDraft' )

        self.assertEqual( response.status_code, 200 )                      # source not in the choices
        self.assertFalse( scenarios_for( self.organization ).filter( label = 'FromDraft' ).exists() )


class NewScenarioPairTests( _NewScenarioBase ):

    def _pair( self, **fields ):
        data = { 'action': 'pair' }
        data.update( { f'pair-{key}': value for key, value in fields.items() } )
        return ScenarioComposeView().post( self._request( 'post', data ) )

    def test_pair_creates_the_chosen_new_combination( self ):
        plans, assumptions = self._plans( 'P1' ), self._assumptions( 'A1' )
        self._scenario( 'S1', plans = plans, assumptions = assumptions )
        spare = self._plans( 'P2' )

        response = self._pair( plans = str( spare.uuid ),
                               assumptions = str( assumptions.uuid ), name = 'Paired' )

        self.assertEqual( response.status_code, 302 )
        paired = scenarios_for( self.organization ).get( label = 'Paired' )
        self.assertEqual( paired.plans_id, spare.id )
        self.assertEqual( paired.assumptions_id, assumptions.id )

    def test_pair_rejects_an_already_used_combination( self ):
        plans, assumptions = self._plans( 'P1' ), self._assumptions( 'A1' )
        self._scenario( 'S1', plans = plans, assumptions = assumptions )   # (P1, A1) is taken
        self._plans( 'P2' )                                                # keeps the page in the pair state

        before   = scenarios_for( self.organization ).count()
        response = self._pair( plans = str( plans.uuid ),
                               assumptions = str( assumptions.uuid ), name = 'Dup combo' )

        self.assertEqual( response.status_code, 200 )                      # server re-checks the pairing
        self.assertEqual( scenarios_for( self.organization ).count(), before )

    def test_pair_rejects_a_duplicate_name( self ):
        plans, assumptions = self._plans( 'P1' ), self._assumptions( 'A1' )
        self._scenario( 'S1', plans = plans, assumptions = assumptions )
        spare = self._plans( 'P2' )

        response = self._pair( plans = str( spare.uuid ),
                               assumptions = str( assumptions.uuid ), name = 'S1' )

        self.assertEqual( response.status_code, 200 )
        self.assertEqual( scenarios_for( self.organization ).filter( label = 'S1' ).count(), 1 )


class NewScenarioStartFreshTests( _NewScenarioBase ):

    def setUp( self ):
        seed_default_parameter_sets()              # start-fresh mints default (seeded) components
        super().setUp()

    def test_start_fresh_mints_a_scenario_and_enters_its_own_build_flow( self ):
        base    = self._scenario( 'Base' )
        before  = scenarios_for( self.organization ).count()
        request = self._request( 'post', { 'action': 'start_fresh', 'fresh-name': 'Fresh' } )
        # Simulate having just edited another scenario, so a stale selection would show the wrong Plans.
        request.session_state.current_plans_uuid       = str( base.plans.uuid )
        request.session_state.current_assumptions_uuid = str( base.assumptions.uuid )

        response = ScenarioComposeView().post( request )

        self.assertEqual( scenarios_for( self.organization ).count(), before + 1 )
        fresh = scenarios_for( self.organization ).get( label = 'Fresh' )
        # A fresh scenario starts unreviewed -- the user must walk every section, unlike a copy (which
        # inherits the source's reviewed state).
        self.assertEqual( fresh.plans.acknowledged_sections, [] )
        self.assertEqual( fresh.assumptions.acknowledged_sections, [] )
        # The interview now targets the fresh scenario's own components, not the previously-selected ones.
        self.assertEqual( request.session_state.editing_scenario, str( fresh.uuid ) )
        self.assertEqual( request.session_state.current_plans_uuid, str( fresh.plans.uuid ) )
        self.assertEqual( request.session_state.current_assumptions_uuid, str( fresh.assumptions.uuid ) )
        self.assertRedirects(
            response,
            reverse( 'interview_section', kwargs = { 'section': first_section_of_flow( 'plans' ).key } ),
            fetch_redirect_response = False )

    def test_start_fresh_with_a_blank_name_uses_a_default( self ):
        self._scenario( 'Base' )
        before = scenarios_for( self.organization ).count()

        response = ScenarioComposeView().post( self._request( 'post', { 'action': 'start_fresh' } ) )

        self.assertEqual( response.status_code, 302 )                      # a default name is minted
        self.assertEqual( scenarios_for( self.organization ).count(), before + 1 )

    def test_start_fresh_rejects_a_duplicate_name( self ):
        self._scenario( 'Base' )                                           # 'Base' is taken
        before = scenarios_for( self.organization ).count()

        response = ScenarioComposeView().post(
            self._request( 'post', { 'action': 'start_fresh', 'fresh-name': 'Base' } ) )

        self.assertEqual( response.status_code, 200 )                      # same validation as Copy/Pair
        self.assertEqual( scenarios_for( self.organization ).count(), before )
