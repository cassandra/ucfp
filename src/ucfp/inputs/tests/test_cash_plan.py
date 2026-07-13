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
from ucfp.inputs.plans.defaults import LIQUID_DRAW_CLASSES, default_drawdown
from ucfp.inputs.plans.schemas import Plans
from ucfp.planning.materialization import _cash_account


def _profile( *holdings ):
    """A minimal stand-in profile: `(handle, asset_class)` pairs the sweep can invest into."""
    assets = [ SimpleNamespace( handle = handle, asset_class = klass ) for handle, klass in holdings ]
    return SimpleNamespace( assets = assets )


class DefaultDrawdownTests( unittest.TestCase ):

    def test_default_is_the_complete_band_waterfall_and_sweep( self ):
        policy = default_drawdown()
        self.assertEqual( policy.cash_floor, Decimal( '25000' ) )
        self.assertEqual( policy.cash_ceiling, Decimal( '50000' ) )
        self.assertEqual( tuple( policy.draw_order ), LIQUID_DRAW_CLASSES )
        self.assertEqual( policy.sweep_allocation,
                          [ ( 'stocks', Decimal( '0.5' ) ), ( 'bonds', Decimal( '0.5' ) ) ] )

    def test_unedited_plan_materializes_the_full_default( self ):
        # a plan with no drawdown still gets the sensible band, waterfall, and 50/50 sweep
        cash = _cash_account( Plans() )
        self.assertEqual( cash.cash_floor, Decimal( '25000' ) )
        self.assertEqual( cash.cash_ceiling, Decimal( '50000' ) )
        self.assertEqual( tuple( cash.draw_order ), LIQUID_DRAW_CLASSES )
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
        self.assertEqual( len( plans.drawdown.draw_order ), len( LIQUID_DRAW_CLASSES ) )
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
        # a stray posted value (e.g. a class not in the liquid set) is filtered out
        form = self._post( '25000', [ 'STOCKS', 'REAL_ESTATE_RENTAL', 'BONDS' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.draw_order, [ AssetClass.STOCKS, AssetClass.BONDS ] )


if __name__ == '__main__':
    unittest.main()
