"""The Cash Plan section (#81): the default drawdown policy and the draw-order form parse.

The engine + schema + materialization already support the cash band; this section is the input UI
that populates `DrawdownPolicy`. The pieces with real logic -- the sensible default, the default
applying to an unedited plan, and the reorderable draw-order parse -- earn a committed test; the
rest is form/template glue. The maximum (ceiling) and the sweep are a later section, so this phase
never persists a ceiling (the engine requires one to come with a sweep)."""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.cash_plan import DrawdownForm
from ucfp.inputs.plans.defaults import LIQUID_DRAW_CLASSES, default_drawdown
from ucfp.inputs.plans.schemas import Plans
from ucfp.planning.materialization import _cash_account


class DefaultDrawdownTests( unittest.TestCase ):

    def test_default_band_and_liquid_waterfall( self ):
        policy = default_drawdown()
        self.assertEqual( policy.cash_floor, Decimal( '25000' ) )
        self.assertIsNone( policy.cash_ceiling )               # no ceiling until it comes with a sweep
        self.assertEqual( tuple( policy.draw_order ), LIQUID_DRAW_CLASSES )
        self.assertEqual( policy.sweep_allocation, [] )

    def test_unedited_plan_materializes_the_default_band( self ):
        # a plan with no drawdown still gets the sensible floor + waterfall (not the empty cash params)
        cash = _cash_account( Plans() )
        self.assertEqual( cash.cash_floor, Decimal( '25000' ) )
        self.assertIsNone( cash.cash_ceiling )                 # no ceiling -> no sweep required
        self.assertEqual( tuple( cash.draw_order ), LIQUID_DRAW_CLASSES )
        self.assertIsNone( cash.sweep_allocation )


class DrawdownFormTests( unittest.TestCase ):

    def _post( self, floor, order, ceiling = '' ):
        data = QueryDict( mutable = True )
        data[ 'cash_floor' ]   = floor
        data[ 'cash_ceiling' ] = ceiling
        data.setlist( 'draw_order', order )
        return DrawdownForm( data, plans = Plans() )

    def test_apply_writes_the_edited_floor_and_reordered_draw_order( self ):
        form = self._post(
            '30000', [ 'STOCKS', 'CDS', 'BONDS', 'DIVIDEND_STOCKS', 'ROTH', 'PRETAX_RETIREMENT' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.cash_floor, Decimal( '30000' ) )
        self.assertEqual( plans.drawdown.draw_order[ 0 ], AssetClass.STOCKS )   # moved to the top
        self.assertEqual( len( plans.drawdown.draw_order ), len( LIQUID_DRAW_CLASSES ) )

    def test_ceiling_is_never_persisted_without_a_sweep( self ):
        # the ceiling field is disabled this phase; even a posted value must not become an invalid
        # ceiling (a ceiling with no sweep) -- it stays None
        form = self._post( '25000', [ c.name for c in LIQUID_DRAW_CLASSES ], ceiling = '50000' )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, plans = form.apply( None, Plans() )
        self.assertIsNone( plans.drawdown.cash_ceiling )
        self.assertEqual( plans.drawdown.sweep_allocation, [] )

    def test_unknown_draw_order_names_are_ignored( self ):
        # a stray posted value (e.g. a class not in the liquid set) is filtered out
        form = self._post( '25000', [ 'STOCKS', 'REAL_ESTATE_RENTAL', 'BONDS' ] )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, plans = form.apply( None, Plans() )
        self.assertEqual( plans.drawdown.draw_order, [ AssetClass.STOCKS, AssetClass.BONDS ] )


if __name__ == '__main__':
    unittest.main()
