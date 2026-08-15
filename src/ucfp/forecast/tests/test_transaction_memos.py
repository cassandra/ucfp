"""Engine-synthesized transaction memos for the per-period accruals and the opening seed -- so the results
drill-down explains each posting rather than showing a blank Description column.

A distributing holding (interest/dividends) and an appreciating one both post to accounts that several
holdings can share (a tax-class income account, the Unrealized Gains equity), so the memo names the source
holding and the rate-on-base that produced the amount. The opening seed records one transaction per seeded
account, so each names its account. The amount itself is the ledger's job; the memo carries the *why*.
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


def _memos( books, needle ):
    return [ txn.description for txn in books.transactions if needle in txn.description ]


class TransactionMemoTests( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        # One minimal run seeding cash (interest) and a brokerage (growth), so one projection exercises
        # the opening seed and both per-period accruals.
        economics = EconomicOutlook.constant( EconomicParameters(
            savings_interest   = Rate( Decimal( '0.03' ) ),
            stock_appreciation = Rate( Decimal( '0.05' ) ) ) )
        parameters = ForecastParameters(
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
            economic_outlook = economics )
        cls.books = Forecast( parameters ).run().books

    def test_distribution_and_growth_memos_name_the_source_rate_and_base( self ):
        # Interest yield on cash and unrealized appreciation on the brokerage: the source, its rate, and
        # the base that produced the amount. Distributions accrue on the period's average balance (here no
        # flows, so the average is the opening); growth accrues on the opening.
        self.assertEqual(
            _memos( self.books, 'distribution' ),
            [ 'Cash distribution: 3% on avg balance $200,000.00' ] )
        self.assertEqual(
            _memos( self.books, 'appreciation' ), [ 'Brokerage appreciation: 5% on $100,000.00' ] )

    def test_opening_seed_memo_names_each_seeded_account( self ):
        openings = set( _memos( self.books, 'opening balance' ) )
        self.assertEqual( openings, { 'Cash opening balance', 'Brokerage opening balance' } )


if __name__ == '__main__':
    unittest.main()
