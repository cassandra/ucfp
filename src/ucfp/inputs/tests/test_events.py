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
from ucfp.forecast.parameters import ScheduledRealization, ScheduledTransfer
from ucfp.inputs.events import EventContributions, SOURCE_ROLE, TARGET_ROLE, TransferEvent
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


if __name__ == '__main__':
    unittest.main()
