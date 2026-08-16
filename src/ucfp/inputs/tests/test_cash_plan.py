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

    def _post( self, floor, order, *, ceiling = '', sweep = () ):
        data = QueryDict( mutable = True )
        data[ 'cash_floor' ]   = floor
        data[ 'cash_ceiling' ] = ceiling
        data.setlist( 'draw_order', order )
        data.setlist( 'sweep_handle', [ handle for handle, _weight in sweep ] )
        data.setlist( 'sweep_weight', [ weight for _handle, weight in sweep ] )
        profile = _profile( ( 'stocks', AssetClass.STOCKS ), ( 'bonds', AssetClass.BONDS ) )
        return DrawdownForm( data, profile = profile, plans = Plans() )

    def test_apply_writes_the_edited_floor_and_reordered_draw_order( self ):
        form = self._post(
            '30000', [ 'STOCKS', 'CDS', 'BONDS', 'DIVIDEND_STOCKS', 'ROTH', 'PRETAX_RETIREMENT' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.cash_floor, Decimal( '30000' ) )
        self.assertEqual( plans.drawdown.draw_order[ 0 ], AssetClass.STOCKS )   # moved to the top
        # The pane posts only the liquid rows; the whole-asset sale sources it does not render are
        # preserved in the stored order after them, so the full source set survives the save.
        self.assertEqual( len( plans.drawdown.draw_order ), len( DRAW_SOURCE_CLASSES ) )
        whole_asset = [ c for c in DRAW_SOURCE_CLASSES if c not in LIQUID_DRAW_CLASSES ]
        self.assertEqual( plans.drawdown.draw_order[ len( LIQUID_DRAW_CLASSES ): ], whole_asset )
        self.assertIsNone( plans.drawdown.cash_ceiling )                        # no ceiling posted -> none kept

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
        # a stray posted value (not a draw-source class at all) is filtered out; the recognized rows
        # lead and the unrendered sources are still preserved after them
        form = self._post( '25000', [ 'STOCKS', 'NONSENSE', 'BONDS' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.draw_order[ :2 ], [ AssetClass.STOCKS, AssetClass.BONDS ] )
        self.assertNotIn( 'NONSENSE', [ c.name for c in plans.drawdown.draw_order ] )
        self.assertEqual( len( plans.drawdown.draw_order ), len( DRAW_SOURCE_CLASSES ) )


if __name__ == '__main__':
    unittest.main()
