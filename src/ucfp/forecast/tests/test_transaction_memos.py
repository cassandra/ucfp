"""Engine-synthesized transaction memos for the per-period accruals -- so the results drill-down explains
each posting rather than showing a blank Description column.

A distributing holding (interest/dividends) and an appreciating one both post to accounts that several
holdings can share (a tax-class income account, the Unrealized Gains equity), so the memo names the source
holding and the rate-on-base that produced the amount. The amount itself is the ledger's job; the memo
carries the *why*.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, Subject
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


def _the_txn( books, needle ):
    """The single transaction whose memo contains `needle` (asserts exactly one, so the memo is
    unambiguous)."""
    matches = [ txn for txn in books.transactions if needle in txn.description ]
    assert len( matches ) == 1, f'expected one {needle!r} memo, found {len( matches )}'
    return matches[ 0 ]


class TransactionMemoTests( unittest.TestCase ):

    def test_distribution_and_growth_memos_name_the_source_rate_and_base( self ):
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _STATUTE,
            subjects      = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets        = [
                AssetParameters(
                    'Cash', AssetClass.CASH, Decimal( '200000' ), Decimal( '200000' ), handle = 'cash' ),
                AssetParameters(
                    'Brokerage', AssetClass.STOCKS, Decimal( '100000' ), Decimal( '100000' ),
                    handle = 'stocks' ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters(
                savings_interest   = Rate( Decimal( '0.03' ) ),
                stock_appreciation = Rate( Decimal( '0.05' ) ) ) ) )
        books = Forecast( params ).run().books

        # Interest yield on cash: the source, its rate, and the opening base that produced the amount.
        self.assertEqual(
            _the_txn( books, 'distribution' ).description, 'Cash distribution: 3% on $200,000.00' )
        # Unrealized appreciation on the brokerage holding, same shape.
        self.assertEqual(
            _the_txn( books, 'appreciation' ).description, 'Brokerage appreciation: 5% on $100,000.00' )


if __name__ == '__main__':
    unittest.main()
