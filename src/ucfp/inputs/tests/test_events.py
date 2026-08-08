"""Plan events (#105): a Transfer's materialization *choice* -- which scheduled event it emits.

The engine already proves each scheduled event behaves correctly (see `forecast/tests/test_events.py`);
what earns a committed test here is the routing decision the inputs layer makes, because it regresses
silently -- a revert to a plain `ScheduledTransfer` for a stock source would make the sale tax-free and
every engine test would still pass. The dispatch keys on the settled `AssetClass` taxonomy, so it is
stable dispatch, not churning model. Only the branch (appreciating vs face-value source) and its
cash-hub-vs-conversion destination sub-rule are pinned here; gain/basis math is the engine's to test.
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ScheduledLoanPayoff, ScheduledRealization, ScheduledTransfer
from ucfp.inputs.events import (
    EventContributions, POSSESSION_ROLE, SOURCE_ROLE, TARGET_ROLE, SellPossessionEvent, TransferEvent )
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.schemas import PlanEvent


def _profile( *holdings ):
    """A minimal stand-in profile: `(handle, asset_class)` pairs a transfer can move between."""
    assets = [ SimpleNamespace( handle = handle, asset_class = klass ) for handle, klass in holdings ]
    return SimpleNamespace( assets = assets )


def _transfer( source, target, amount = Decimal( '50000' ) ):
    return PlanEvent( kind = EventKind.TRANSFER, date = date( 2030, 3, 1 ), amount = amount,
                      selections = { SOURCE_ROLE: source, TARGET_ROLE: target } )


def _materialize( profile, event ):
    into = EventContributions()
    TransferEvent().contribute( event, profile, {}, into )
    return into.scheduled_events


class TransferMaterializationTests( unittest.TestCase ):

    def test_appreciating_source_to_cash_realizes_into_the_cash_hub( self ):
        profile = _profile( ( 'stk', AssetClass.STOCKS ), ( 'cash', AssetClass.CASH ) )
        events  = _materialize( profile, _transfer( 'stk', 'cash' ) )
        self.assertEqual( len( events ), 1 )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.holding, 'stk' )
        self.assertEqual( realization.amount, Decimal( '50000' ) )
        self.assertIsNone( realization.destination )       # proceeds to the cash hub

    def test_appreciating_source_to_holding_is_a_conversion( self ):
        # a non-cash target keeps the destination handle, so the proceeds re-establish basis there
        profile = _profile( ( 'stk', AssetClass.STOCKS ), ( 'roth', AssetClass.ROTH ) )
        events  = _materialize( profile, _transfer( 'stk', 'roth' ) )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.destination, 'roth' )

    def test_face_value_source_stays_a_plain_transfer( self ):
        # a CD (or cash) source carries no embedded gain -- a plain, no-tax value move
        profile = _profile( ( 'cd', AssetClass.CDS ), ( 'stk', AssetClass.STOCKS ) )
        events  = _materialize( profile, _transfer( 'cd', 'stk' ) )
        self.assertEqual( len( events ), 1 )
        transfer = events[ 0 ]
        self.assertIsInstance( transfer, ScheduledTransfer )
        self.assertEqual( ( transfer.source, transfer.target, transfer.amount ),
                          ( 'cd', 'stk', Decimal( '50000' ) ) )


def _sale_profile( possessions, debts = () ):
    """A stand-in profile for a possession sale: possessions as (handle, class, name) and any securing
    debts as (handle, secured_asset, name)."""
    return SimpleNamespace(
        assets   = [ SimpleNamespace( handle = h, asset_class = k, name = n ) for h, k, n in possessions ],
        debts    = [ SimpleNamespace( handle = h, secured_asset = s, name = n ) for h, s, n in debts ],
        subjects = [] )


def _sell( possession_handle ):
    return PlanEvent( kind = EventKind.SELL_POSSESSION, date = date( 2030, 6, 1 ),
                      selections = { POSSESSION_ROLE: possession_handle } )


def _sale_events( profile, event ):
    into = EventContributions()
    SellPossessionEvent().contribute( event, profile, {}, into )
    return into.scheduled_events


class SellPossessionTests( unittest.TestCase ):
    """A possession sale mirrors a property sale: realize the whole holding at its projected value, and
    pay off any loan secured against it. The routing (whole-holding realization + secured-loan payoff) is
    what regresses silently, so it earns a test here; the gain/tax math is the engine's."""

    def test_a_sale_realizes_the_whole_possession( self ):
        profile     = _sale_profile( [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ] )
        events      = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( len( events ), 1 )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.holding, 'possession-1' )
        self.assertIsNone( realization.amount )   # None -> the whole holding at its projected value

    def test_a_secured_possession_also_pays_off_its_loan( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', 'possession-1', 'Car loan' ) ] )      # secured against the car
        events  = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( [ type( e ).__name__ for e in events ],
                          [ 'ScheduledRealization', 'ScheduledLoanPayoff' ] )
        self.assertIsInstance( events[ 1 ], ScheduledLoanPayoff )
        self.assertEqual( events[ 1 ].loan, 'debt-1' )

    def test_a_sale_records_its_date_for_running_cost_clipping( self ):
        # The sale date is recorded so materialization ends the possession's running costs at it (a sold
        # car stops incurring insurance/fuel), mirroring a property sale's operating-cost clip.
        profile = _sale_profile( [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ] )
        into    = EventContributions()
        SellPossessionEvent().contribute( _sell( 'possession-1' ), profile, {}, into )
        self.assertEqual( into.possession_sales, { 'possession-1' : date( 2030, 6, 1 ) } )

    def test_an_unsecured_possession_emits_only_the_realization( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', None, 'Credit card' ) ] )             # a debt not secured against the car
        events  = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( [ type( e ).__name__ for e in events ], [ 'ScheduledRealization' ] )

    def test_the_summary_names_the_item_and_flags_a_payoff( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', 'possession-1', 'Car loan' ) ] )
        summary = SellPossessionEvent().summary( _sell( 'possession-1' ), profile )
        self.assertIn( 'Sell Car in 2030', summary )
        self.assertIn( 'loan paid off', summary )

    def test_offerable_only_when_a_possession_exists( self ):
        self.assertFalse( SellPossessionEvent().offerable( _sale_profile( [] ) ) )
        self.assertTrue( SellPossessionEvent().offerable(
            _sale_profile( [ ( 'possession-1', AssetClass.COLLECTIBLES, 'Ring' ) ] ) ) )


if __name__ == '__main__':
    unittest.main()
