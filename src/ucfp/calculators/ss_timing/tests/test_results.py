"""The results page: the heatmap / ranked view-model (`results.py`), the results render for a couple, and
the drill-in endpoint that swaps one strategy's detail. The view-model is built over a hand-made
Comparison (no engine); the view tests drive the real sweep through the session.
"""
import json
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from ucfp.calculators.ss_timing import results
from ucfp.calculators.ss_timing.compute import Claimant, Comparison, Strategy

_HIGHER = Claimant( 'Higher', 1960, Decimal( '3000' ), 85 )
_LOWER  = Claimant( 'Lower', 1962, Decimal( '1000' ), 88 )


def _strategy( claim_ages, present_value ) -> Strategy:
    return Strategy( claim_ages = claim_ages, raw_total = Decimal( present_value ),
                     present_value = Decimal( present_value ), year_benefits = () )


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
        self.assertEqual( rows[ 0 ].rank, 1 )
        self.assertTrue( rows[ 0 ].is_best )
        self.assertEqual( rows[ 0 ].ages, ( 70, 70 ) )
        self.assertEqual( len( rows ), 10 )                 # _RANK_LIMIT


def _couple_form_data() -> dict:
    return { 'household' : 'couple',
             's0_birth_year' : '1960', 's0_pia' : '3000', 's0_life' : '84',
             's1_birth_year' : '1962', 's1_pia' : '1200', 's1_life' : '88',
             'cola' : '2.5', 'inflation' : '2.5', 'benefits_payable' : '100', 'reduction_year' : '2033' }


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

    def test_the_drill_in_endpoint_swaps_one_strategy_detail( self ):
        self._submit()
        response = self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '67-67' ] ),
            HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        self.assertEqual( response.status_code, 200 )
        detail = json.loads( response.content )[ 'replace' ][ 'ss-detail' ]
        self.assertIn( 'Total', detail )
        self.assertIn( 'Lifetime total', detail )

    def test_a_bad_or_mismatched_combo_is_not_found( self ):
        self._submit()
        self.assertEqual( self.client.get(
            reverse( 'calculators:ss_timing:detail', args = [ '99-99' ] ) ).status_code, 404 )
        self.assertEqual( self.client.get(                                  # single arity for a couple
            reverse( 'calculators:ss_timing:detail', args = [ '67' ] ) ).status_code, 404 )
