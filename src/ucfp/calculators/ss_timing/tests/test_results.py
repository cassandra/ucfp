"""The results page: the heatmap / ranked view-model (`results.py`), the results render for a couple, and
the drill-in endpoint that swaps one strategy's detail. The view-model is built over a hand-made
Comparison (no engine); the view tests drive the real sweep through the session.
"""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from organization.models import Organization

from ucfp.calculators.ss_timing import results
from ucfp.calculators.ss_timing.compute import Claimant, Comparison, Strategy

User = get_user_model()

_HIGHER = Claimant( 'Higher', 1960, Decimal( '3000' ), 85 )
_LOWER  = Claimant( 'Lower', 1962, Decimal( '1000' ), 88 )


def _strategy( claim_ages, value, effective_value = None ) -> Strategy:
    effective_value = value if effective_value is None else effective_value
    return Strategy( claim_ages = claim_ages, raw_total = Decimal( value ),
                     present_value = Decimal( value ), effective_value = Decimal( effective_value ),
                     year_benefits = () )


def _couple_comparison() -> Comparison:
    # Distinct present values so the best is unambiguous and the ramp spreads across buckets.
    strategies = tuple(
        _strategy( ( higher, lower ), 100000 + higher * 100 + lower )
        for higher in range( 62, 71 ) for lower in range( 62, 71 ) )
    return Comparison( claimants = ( _HIGHER, _LOWER ), strategies = strategies )


class HeatmapViewModelTest( SimpleTestCase ):

    def test_a_couple_grid_is_nine_by_nine_oriented_higher_then_lower( self ):
        comparison = _couple_comparison()
        grid = results.heatmap( comparison, results.combo_of( comparison.best.claim_ages ) )
        self.assertEqual( len( grid ), 9 )
        self.assertTrue( all( len( row ) == 9 for row in grid ) )
        self.assertEqual( ( grid[ 0 ][ 0 ].higher_age, grid[ 0 ][ 0 ].lower_age ), ( 62, 62 ) )
        self.assertEqual( ( grid[ 8 ][ 8 ].higher_age, grid[ 8 ][ 8 ].lower_age ), ( 70, 70 ) )

    def test_the_best_cell_is_marked_and_selected_and_buckets_span_the_ramp( self ):
        comparison = _couple_comparison()
        grid  = results.heatmap( comparison, results.combo_of( comparison.best.claim_ages ) )
        cells = [ cell for row in grid for cell in row ]
        best  = [ cell for cell in cells if cell.is_best ]
        self.assertEqual( [ ( cell.higher_age, cell.lower_age ) for cell in best ], [ ( 70, 70 ) ] )
        self.assertTrue( best[ 0 ].is_selected )
        buckets = { cell.bucket for cell in cells }
        self.assertEqual( min( buckets ), 0 )
        self.assertEqual( max( buckets ), 6 )               # _HEAT_BUCKETS - 1

    def test_a_single_person_grid_is_one_strip_without_a_lower_age( self ):
        comparison = Comparison(
            claimants = ( _HIGHER, ),
            strategies = tuple( _strategy( ( age, ), 1000 + age ) for age in range( 62, 71 ) ) )
        grid = results.heatmap( comparison, results.combo_of( comparison.best.claim_ages ) )
        self.assertEqual( len( grid ), 1 )
        self.assertEqual( len( grid[ 0 ] ), 9 )
        self.assertIsNone( grid[ 0 ][ 0 ].lower_age )

    def test_ranked_lists_the_best_first( self ):
        comparison = _couple_comparison()
        rows = results.ranked( comparison, results.combo_of( comparison.best.claim_ages ) )
        self.assertEqual( rows[ 0 ].rank, 1 )                            # rank 1 is the best, by order
        self.assertEqual( rows[ 0 ].ages, ( 70, 70 ) )
        self.assertEqual( len( rows ), 10 )                 # _RANK_LIMIT

    def test_a_selection_in_the_top_ten_adds_no_extra_row( self ):
        comparison = _couple_comparison()
        rows = results.ranked( comparison, results.combo_of( comparison.best.claim_ages ) )
        self.assertEqual( len( rows ), 10 )
        self.assertFalse( any( row.beyond_top for row in rows ) )

    def test_a_selection_outside_the_top_ten_is_appended_with_its_true_rank( self ):
        # (62, 62) is the worst combo here (value rises with age), so selecting it appends an 11th row
        # carrying its real rank -- so its lifetime figures stay visible without a top-ten place.
        rows = results.ranked( _couple_comparison(), '62-62' )
        self.assertEqual( len( rows ), 11 )
        extra = rows[ -1 ]
        self.assertTrue( extra.beyond_top )
        self.assertTrue( extra.is_selected )
        self.assertEqual( extra.combo, '62-62' )
        self.assertEqual( extra.rank, 81 )                  # the true rank, not 11
        self.assertFalse( any( row.beyond_top for row in rows[ :10 ] ) )

    def test_the_heatmap_marks_and_shades_by_effective_value_not_present( self ):
        # Present value rises with age (best at 70) while effective value falls (best at 62); the mark and
        # the top shade must follow effective value -- the decision metric -- not present value.
        comparison = Comparison(
            claimants = ( _HIGHER, ),
            strategies = tuple( _strategy( ( age, ), value = 100 + age, effective_value = 200 - age )
                                for age in range( 62, 71 ) ) )
        cells = [ cell for row in results.heatmap(
            comparison, results.combo_of( comparison.best.claim_ages ) ) for cell in row ]
        self.assertEqual( next( cell for cell in cells if cell.is_best ).higher_age, 62 )
        self.assertEqual( max( cells, key = lambda cell: cell.bucket ).higher_age, 62 )


def _couple_form_data() -> dict:
    return { 'household' : 'couple', 'life_expectancy_mode' : 'specific',
             's0_birth_year' : '1960', 's0_pia' : '3000', 's0_life' : '84',
             's1_birth_year' : '1962', 's1_pia' : '1200', 's1_life' : '88',
             'inflation' : '2.5', 'expected_return' : '4.5',
             'benefits_payable' : '100', 'reduction_year' : '2033' }


def _actuarial_couple_form_data() -> dict:
    # A couple estimating life expectancy from the tables (no entered ages): the higher earner male, the
    # lower female, both average longevity.
    return { 'household' : 'couple', 'life_expectancy_mode' : 'actuarial',
             's0_birth_year' : '1960', 's0_pia' : '3000', 's0_sex' : 'male', 's0_longevity' : '0',
             's1_birth_year' : '1962', 's1_pia' : '1200', 's1_sex' : 'female', 's1_longevity' : '0',
             'inflation' : '2.5', 'expected_return' : '4.5',
             'benefits_payable' : '100', 'reduction_year' : '2033' }


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ResultsRenderTest( TestCase ):

    def _submit( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _couple_form_data() )

    def test_the_couple_results_render_the_heatmap_and_detail( self ):
        self._submit()
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'ss-hm-cell' )                       # the heatmap grid
        self.assertContains( response, 'data-combo' )
        self.assertContains( response, 'Survivor' )                         # the couple detail column

    def test_the_results_show_the_opportunity_cost_framing( self ):
        self._submit()                                                      # return 4.5% over 2.5% inflation
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertContains( response, 'Asset return' )                     # the recap chip ...
        self.assertContains( response, 'Effective<br>value' )               # ... and the third ranked column

    def test_a_return_equal_to_inflation_shows_only_total_and_present_value( self ):
        # Setting the asset return equal to inflation is the zero-real-opportunity-cost view: no asset-return
        # chip and no Effective value column.
        data = _couple_form_data()
        data[ 'expected_return' ] = data[ 'inflation' ]
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), data )
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertNotContains( response, 'Asset return' )
        self.assertNotContains( response, 'Effective<br>value' )

    def test_the_drill_in_endpoint_swaps_one_strategy_detail( self ):
        self._submit()
        response = self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '67-67' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        self.assertEqual( response.status_code, 200 )
        detail = json.loads( response.content )[ 'replace' ][ 'ss-detail' ]
        self.assertIn( 'Total', detail )
        self.assertIn( 'Present value', detail )

    def test_drilling_into_an_out_of_top_ten_cell_swaps_in_its_rank_row( self ):
        # The drill-in re-renders the ranked table too, so an out-of-top-ten pick (claiming both at 62)
        # appears as the highlighted 11th row -- its figures stay reachable though the year-by-year no
        # longer carries totals.
        self._submit()
        payload = json.loads( self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '62-62' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' ).content )[ 'replace' ]
        self.assertIn( 'ss-detail', payload )
        self.assertIn( 'ss-rank', payload )
        self.assertIn( 'beyond', payload[ 'ss-rank' ] )                     # the 11th row's visual break
        self.assertIn( 'data-combo="62-62"', payload[ 'ss-rank' ] )

    def test_the_specific_mode_methodology_omits_the_mortality_basis( self ):
        # The Methodology section always explains the value figures and the SS adjustment, but the
        # life-expectancy/mortality paragraph is actuarial-only (specific mode enters ages directly).
        self._submit()                                                     # specific couple
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertContains( response, 'Methodology' )
        self.assertNotContains( response, 'period life table' )

    def test_the_year_by_year_is_income_only_no_totals_or_effective_value( self ):
        # The year-by-year is an income picture: the lifetime total and the effective value (the decision
        # figures) live once, in the Top strategies table, and must not reappear per-year -- even with the
        # opportunity cost on -- so nothing there competes with or contradicts the ranked figure.
        self._submit()                                                      # return 4.5% over 2.5% inflation
        detail = json.loads( self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '67-67' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' ).content )[ 'replace' ][ 'ss-detail' ]
        self.assertNotIn( 'Lifetime total', detail )
        self.assertNotIn( 'Effective value', detail )

    def test_a_bad_or_mismatched_combo_is_not_found( self ):
        self._submit()
        self.assertEqual( self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '99-99' ] ) ).status_code, 404 )
        self.assertEqual( self.client.get(                                  # single arity for a couple
            reverse( 'calculators:ss_timing:detail', args = [ '67' ] ) ).status_code, 404 )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ActuarialResultsTest( TestCase ):
    """The actuarial basis on the results page: the recap reports the derived life expectancy, and the
    year-by-year is a representative deterministic lifetime (real income + a real survivor step-up), not the
    survival-blended average that no real year would show."""

    def _submit( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _actuarial_couple_form_data() )

    def test_the_recap_reports_the_estimated_life_expectancy( self ):
        self._submit()
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertContains( response, 'Life expectancy' )
        self.assertContains( response, 'male, average' )                    # the higher earner's basis words

    def test_the_figures_are_framed_as_expected_values( self ):
        self._submit()
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertContains( response, 'Expected lifetime benefit' )       # the heatmap eyebrow
        self.assertContains( response, 'expectancy probabilities' )         # the expected-value framing

    def test_the_methodology_section_documents_the_mortality_basis( self ):
        # The predictive life-expectancy method lives in the page Methodology (not the per-strategy modal):
        # the SSA life-table citation, cross-check, and the couple simplification.
        self._submit()
        response = self.client.get( reverse( 'calculators:ss_timing:results' ) )
        self.assertContains( response, 'Methodology' )
        self.assertContains( response, 'period life table' )
        self.assertContains( response, 'table4c6' )                        # the SSA life-table URL
        self.assertContains( response, 'independent' )                     # the couple mortality note

    def test_the_year_by_year_is_a_representative_lifetime_with_a_survivor_step_up( self ):
        self._submit()
        detail = json.loads( self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '70-67' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' ).content )[ 'replace' ][ 'ss-detail' ]
        self.assertIn( 'representative lifetime', detail )                  # framed as one path, not the mean
        self.assertIn( 'transition', detail )                              # the survivor row is flagged
        self.assertNotIn( 'Lifetime total', detail )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class ResultsPathBackTest( TestCase ):
    """The onward path from this standalone calculator, split by purpose: an anonymous visitor gets a
    conversion upsell to the full planner, placed at the results/detail seam; a signed-in visitor gets a
    quiet dashboard breadcrumb at the top -- wayfinding, not a pitch."""

    def _submit_and_get( self ):
        self.client.post( reverse( 'calculators:ss_timing:inputs' ), _couple_form_data() )
        return self.client.get( reverse( 'calculators:ss_timing:results' ) )

    def test_an_anonymous_visitor_is_upsold_to_the_full_planner( self ):
        response = self._submit_and_get()
        self.assertContains( response, 'ss-onward' )                    # the upsell band
        self.assertContains( response, reverse( 'explain' ) )
        self.assertContains( response, 'See how it works' )
        self.assertNotContains( response, 'aria-label="breadcrumb"' )   # no signed-in breadcrumb

    def test_a_signed_in_visitor_gets_a_dashboard_breadcrumb( self ):
        user = User.objects.create_user( email = 'owner@x.test', password = 'x' )
        Organization.objects.create_for_owner( user, name = 'Mine' )
        self.client.force_login( user )
        response = self._submit_and_get()
        self.assertContains( response, 'aria-label="breadcrumb"' )      # the breadcrumb nav
        self.assertContains( response, reverse( 'dashboard' ) )
        self.assertNotContains( response, 'ss-onward' )                 # no anonymous upsell band
