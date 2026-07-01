"""Tests for the cash sweep -- the surplus side of the cash band.

When cash rises above the ceiling, the excess is invested into the sweep account at cost (the
mirror of the funding draw, which refills to the floor). The key correctness property: the
swept amount becomes the holding's cost basis, so a later sale taxes only the gain -- the
already-taxed swept principal is not taxed again. The floor/ceiling are today's-dollars
buffers grown by inflation.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetAllocation,
    AssetParameters,
    CashAccountParameters,
    ForecastParameters,
    ScheduledRealization,
    Subject,
)
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )


def _to( handle ):
    """A whole-surplus allocation to one holding (100%)."""
    return AssetAllocation( ( ( handle, Decimal( '1' ) ), ) )


def _holding( reader, handle ):
    return reader.chart.account( handle )


class CashSweepTests( unittest.TestCase ):

    def test_surplus_above_ceiling_is_invested( self ):
        # 200k cash, no spending: cash above the 50k ceiling is swept into the brokerage
        reader = Bookkeeper( Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '200000' ), Decimal( '200000' ) ),
                AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'brokerage' ) ],
            cash_account  = CashAccountParameters(
                cash_ceiling = Decimal( '50000' ), sweep_allocation = _to( 'brokerage' ) ),
        ) ).run().books )
        ledger = reader.ledger
        through = date( 2026, 12, 31 )
        # cash drops to the ceiling; the 150k surplus lands in the brokerage
        self.assertEqual(
            ledger.market_value( reader.chart.cash_account(), through = through ), Decimal( '50000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'brokerage' ), through = through ),
            Decimal( '150000' ) )
        reader.assert_balanced()

    def test_no_sweep_when_cash_below_ceiling( self ):
        reader = Bookkeeper( Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '30000' ), Decimal( '30000' ) ),
                AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'brokerage' ) ],
            cash_account  = CashAccountParameters(
                cash_ceiling = Decimal( '50000' ), sweep_allocation = _to( 'brokerage' ) ),
        ) ).run().books )
        self.assertEqual(
            reader.ledger.market_value(
                _holding( reader, 'brokerage' ), through = date( 2026, 12, 31 ) ), Decimal( '0' ) )

    def test_swept_amount_is_basis_so_only_gain_is_taxed_on_sale( self ):
        # sweep 100k surplus into the brokerage (basis 100k), grow 10%, then sell it all next
        # year -> only the 10k gain is a long-term gain; the 100k swept principal is not retaxed
        reader = Bookkeeper( Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '150000' ), Decimal( '150000' ) ),
                AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'brokerage' ) ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( stock_appreciation = Rate( Decimal( '0.10' ) ) ) ),
            cash_account  = CashAccountParameters(
                cash_ceiling = Decimal( '50000' ), sweep_allocation = _to( 'brokerage' ) ),
            events        = [ ScheduledRealization( date( 2027, 12, 1 ), 'brokerage', Decimal( '110000' ) ) ],
        ) ).run().books )
        long_term = reader.chart.income_account( IncomeTaxClass.LONG_TERM_GAINS )
        # 100k swept in 2026 -> grows to 110k by the 2027 sale -> only the 10k gain is recognized
        self.assertEqual( reader.ledger.natural_balance( long_term ), Decimal( '10000' ) )

    def test_surplus_is_split_across_the_allocation( self ):
        # 250k cash, 50k ceiling -> 200k surplus split 40% stocks / 40% bonds / 20% CDs
        reader = Bookkeeper( Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '250000' ), Decimal( '250000' ) ),
                AssetParameters( 'Stocks', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'stocks' ),
                AssetParameters( 'Bonds', AssetClass.BONDS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'bonds' ),
                AssetParameters( 'CDs', AssetClass.CDS, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'cds' ) ],
            cash_account  = CashAccountParameters(
                cash_ceiling     = Decimal( '50000' ),
                sweep_allocation = AssetAllocation( (
                    ( 'stocks', Decimal( '0.4' ) ),
                    ( 'bonds', Decimal( '0.4' ) ),
                    ( 'cds', Decimal( '0.2' ) ) ) ) ),
        ) ).run().books )
        ledger = reader.ledger
        through = date( 2026, 12, 31 )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'stocks' ), through = through ), Decimal( '80000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'bonds' ), through = through ), Decimal( '80000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'cds' ), through = through ), Decimal( '40000' ) )
        self.assertEqual(
            ledger.market_value( reader.chart.cash_account(), through = through ), Decimal( '50000' ) )
        reader.assert_balanced()


class CashSweepValidationTests( unittest.TestCase ):

    def _run( self, cash_account, assets ):
        Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = assets,
            cash_account  = cash_account,
        ) ).run()

    def test_ceiling_below_floor_is_rejected( self ):
        assets = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                   AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                                    handle = 'brokerage' ) ]
        with self.assertRaises( ValueError ):
            self._run(
                CashAccountParameters(
                    cash_floor = Decimal( '50000' ), cash_ceiling = Decimal( '10000' ),
                    sweep_allocation = _to( 'brokerage' ) ),
                assets )

    def test_sweep_into_a_retirement_account_is_rejected( self ):
        assets = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                   AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                                    handle = '401k', owner_handle = 'subject-a' ) ]
        with self.assertRaises( ValueError ):
            self._run(
                CashAccountParameters( cash_ceiling = Decimal( '50000' ), sweep_allocation = _to( '401k' ) ),
                assets )


if __name__ == '__main__':
    unittest.main()
