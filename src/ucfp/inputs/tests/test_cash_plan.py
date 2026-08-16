"""The Cash Plan section (#81): the default drawdown policy, the draw-order parse, and the sweep.

The engine + schema + materialization already support the cash band and sweep; this section is the
input UI that populates `DrawdownPolicy`. The pieces with real logic -- the complete default, that
default applying to an unedited plan, the reorderable draw-order parse, the sweep normalization, and
the maximum-requires-a-sweep validation -- earn a committed test; the rest is form/template glue."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.cash_plan import DrawdownForm
from ucfp.inputs.plans.defaults import DRAW_SOURCE_CLASSES, LIQUID_DRAW_CLASSES, default_drawdown
from ucfp.inputs.plans.schemas import Plans
from ucfp.planning.materialization import _cash_account


def _profile( *holdings ):
    """A minimal stand-in profile: `(handle, asset_class)` pairs the sweep can invest into."""
    assets = [ SimpleNamespace( handle = handle, asset_class = klass ) for handle, klass in holdings ]
    return SimpleNamespace( assets = assets )


class DefaultDrawdownTests( unittest.TestCase ):

    def test_default_is_the_complete_band_waterfall_and_sweep( self ):
        policy = default_drawdown()
        self.assertEqual( policy.cash_floor, Decimal( '0' ) )
        self.assertEqual( policy.cash_ceiling, Decimal( '25000' ) )
        self.assertEqual( tuple( policy.draw_order ), DRAW_SOURCE_CLASSES )   # exhausts every source in turn
        self.assertEqual( policy.retained, [] )                               # nothing held back by default
        self.assertEqual( policy.sweep_allocation,
                          [ ( 'stocks', Decimal( '0.5' ) ), ( 'bonds', Decimal( '0.5' ) ) ] )

    def test_draw_sources_are_the_liquid_classes_plus_the_whole_asset_sale_sources( self ):
        # The liquid classes lead (a slice sells readily); the indivisible whole-asset sale sources
        # follow, residence last, and exactly the liquid classes are the partially-drawable ones.
        self.assertEqual( DRAW_SOURCE_CLASSES[ : len( LIQUID_DRAW_CLASSES ) ], LIQUID_DRAW_CLASSES )
        self.assertEqual( DRAW_SOURCE_CLASSES[ -1 ], AssetClass.REAL_ESTATE_RESIDENCE )
        partial = tuple( c for c in DRAW_SOURCE_CLASSES if c.supports_partial_draw )
        self.assertEqual( partial, LIQUID_DRAW_CLASSES )

    def test_unedited_plan_materializes_the_full_default( self ):
        # a plan with no drawdown still gets the sensible band, waterfall, and 50/50 sweep
        cash = _cash_account( Plans() )
        self.assertEqual( cash.cash_floor, Decimal( '0' ) )
        self.assertEqual( cash.cash_ceiling, Decimal( '25000' ) )
        self.assertEqual( tuple( cash.draw_order ), DRAW_SOURCE_CLASSES )
        self.assertEqual( cash.sweep_allocation.weights,
                          ( ( 'stocks', Decimal( '0.5' ) ), ( 'bonds', Decimal( '0.5' ) ) ) )


class DrawdownFormTests( unittest.TestCase ):

    def _post( self, floor, order, *, ceiling = '', sweep = (), retained = () ):
        data = QueryDict( mutable = True )
        data[ 'cash_floor' ]   = floor
        data[ 'cash_ceiling' ] = ceiling
        data.setlist( 'draw_order', order )
        data.setlist( 'retained', list( retained ) )
        data.setlist( 'sweep_handle', [ handle for handle, _weight in sweep ] )
        data.setlist( 'sweep_weight', [ weight for _handle, weight in sweep ] )
        profile = _profile( ( 'stocks', AssetClass.STOCKS ), ( 'bonds', AssetClass.BONDS ) )
        return DrawdownForm( data, profile = profile, plans = Plans() )

    def test_apply_writes_the_edited_floor_and_reordered_draw_order( self ):
        # the pane renders every source; posting the full set with Stocks moved up stores that order
        order = [ 'STOCKS' ] + [ c.name for c in DRAW_SOURCE_CLASSES if c is not AssetClass.STOCKS ]
        form  = self._post( '30000', order )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.cash_floor, Decimal( '30000' ) )
        self.assertEqual( plans.drawdown.draw_order[ 0 ], AssetClass.STOCKS )   # moved to the top
        self.assertEqual( len( plans.drawdown.draw_order ), len( DRAW_SOURCE_CLASSES ) )
        self.assertEqual( plans.drawdown.retained, [] )                         # none retained
        self.assertIsNone( plans.drawdown.cash_ceiling )                        # no ceiling posted -> none kept

    def test_retaining_a_source_keeps_its_slot_disables_its_row_and_drops_it_from_the_engine( self ):
        # Retaining the residence persists the full order (its slot preserved) plus the retained mark; the
        # engine's list drops it; its row renders disabled with no rank while the enabled rows stay 1..N-1.
        order = [ c.name for c in DRAW_SOURCE_CLASSES ]
        form  = self._post( '25000', order, retained = [ 'REAL_ESTATE_RESIDENCE' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( len( plans.drawdown.draw_order ), len( DRAW_SOURCE_CLASSES ) )   # slot preserved
        self.assertEqual( plans.drawdown.retained, [ AssetClass.REAL_ESTATE_RESIDENCE ] )
        engine_order = _cash_account( plans ).draw_order
        self.assertNotIn( AssetClass.REAL_ESTATE_RESIDENCE, engine_order )                 # engine never sees it
        self.assertEqual( len( engine_order ), len( DRAW_SOURCE_CLASSES ) - 1 )
        rows = { row[ 'value' ] : row for row in DrawdownForm( None, plans = plans ).draw_rows }
        self.assertFalse( rows[ 'REAL_ESTATE_RESIDENCE' ][ 'enabled' ] )
        self.assertIsNone( rows[ 'REAL_ESTATE_RESIDENCE' ][ 'rank' ] )
        ranks = [ row[ 'rank' ] for row in DrawdownForm( None, plans = plans ).draw_rows if row[ 'enabled' ] ]
        self.assertEqual( ranks, list( range( 1, len( DRAW_SOURCE_CLASSES ) ) ) )          # 1..N-1, contiguous

    def test_a_retained_name_outside_the_posted_order_is_dropped( self ):
        # retained is bounded to the posted order, so a stray mark cannot persist without a matching row
        form = self._post( '25000', [ c.name for c in LIQUID_DRAW_CLASSES ],
                           retained = [ 'STOCKS', 'REAL_ESTATE_RESIDENCE' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.retained, [ AssetClass.STOCKS ] )   # residence absent from the order

    def test_rows_show_group_labels_not_the_verbose_real_estate_catalog_labels( self ):
        labels = { row[ 'value' ] : row[ 'label' ] for row in DrawdownForm( None, plans = Plans() ).draw_rows }
        self.assertEqual( labels[ 'REAL_ESTATE_RESIDENCE' ], 'Residence' )
        self.assertEqual( labels[ 'REAL_ESTATE_SECOND_HOME' ], 'Second Homes' )   # plural, per the Profile panes
        self.assertEqual( labels[ 'REAL_ESTATE_RENTAL' ], 'Rentals' )
        self.assertEqual( labels[ 'PRECIOUS_METALS' ], 'Precious Metals' )        # falls through to the catalog label

    def test_apply_normalizes_the_posted_sweep_to_fractions_summing_to_one( self ):
        form = self._post( '25000', [ c.name for c in LIQUID_DRAW_CLASSES ],
                           ceiling = '50000', sweep = [ ( 'bonds', '60' ), ( 'stocks', '40' ) ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.cash_ceiling, Decimal( '50000' ) )
        self.assertEqual( plans.drawdown.sweep_allocation,
                          [ ( 'bonds', Decimal( '0.6' ) ), ( 'stocks', Decimal( '0.4' ) ) ] )
        self.assertEqual( sum( weight for _handle, weight in plans.drawdown.sweep_allocation ), Decimal( '1' ) )

    def test_a_ceiling_with_no_sweep_is_dropped_not_blocked( self ):
        # non-blocking: an orphaned maximum (the engine requires a sweep to invest into) is not an
        # error mid-entry; it is simply stored as no cap until a holding is chosen
        form = self._post( '25000', [ c.name for c in LIQUID_DRAW_CLASSES ], ceiling = '50000' )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertIsNone( plans.drawdown.cash_ceiling )
        self.assertEqual( plans.drawdown.sweep_allocation, [] )

    def test_unknown_sweep_handles_are_ignored( self ):
        # a posted handle not among the profile's sweepable holdings is filtered out
        form = self._post( '25000', [ c.name for c in LIQUID_DRAW_CLASSES ],
                           ceiling = '50000', sweep = [ ( 'stocks', '50' ), ( 'gold', '50' ) ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.sweep_allocation, [ ( 'stocks', Decimal( '1' ) ) ] )

    def test_unknown_draw_order_names_are_ignored( self ):
        # a stray posted value (not a draw-source class at all) is filtered out
        form = self._post( '25000', [ 'STOCKS', 'NONSENSE', 'BONDS' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.draw_order, [ AssetClass.STOCKS, AssetClass.BONDS ] )


if __name__ == '__main__':
    unittest.main()
