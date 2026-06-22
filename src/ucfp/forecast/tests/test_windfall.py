"""Tests for one-time windfalls -- value received from outside, landing in cash.

A windfall is the non-recurring counterpart of an income stream: a taxable windfall (its
`income_tax_class` set) credits that revenue account and is taxed at the year close; a
non-taxable one (a gift or US inheritance, `income_tax_class` None) credits the External
Receipts equity account and is never taxed. Both raise cash and net worth by the amount
(before any tax).
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass, SystemAccountRole
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    ScheduledWindfall,
    Subject,
)
from ucfp.tax.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile


def _holding( reader, handle ):
    return reader.chart.account( handle )


class WindfallTests( unittest.TestCase ):

    def _run( self, windfall, end_date = date( 2026, 6, 30 ) ):
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = end_date,
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1960, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ),
                                 handle = 'cash' ) ],
            events        = [ windfall ],
        )
        return Bookkeeper( Forecast( parameters ).run().books )

    def test_nontaxable_windfall_credits_equity_and_raises_cash( self ):
        # a half-year horizon (no year close) isolates the inflow from any tax
        reader = self._run(
            ScheduledWindfall( date( 2026, 3, 1 ), Decimal( '100000' ) ) )
        ledger = reader.ledger
        through = date( 2026, 6, 30 )
        external = reader.chart.system_account( SystemAccountRole.EXTERNAL_RECEIPTS )
        # cash rises by the windfall; the balancing credit lands in External Receipts equity
        self.assertEqual( ledger.market_value( _holding( reader, 'cash' ), through = through ),
                          Decimal( '110000' ) )
        self.assertEqual( ledger.natural_balance( external ), Decimal( '100000' ) )
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '110000' ) )

    def test_taxable_windfall_credits_revenue( self ):
        reader = self._run(
            ScheduledWindfall( date( 2026, 3, 1 ), Decimal( '100000' ), IncomeTaxClass.ORDINARY ) )
        ledger = reader.ledger
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY )
        # the windfall is recognized as ordinary revenue (its tax falls due at the year close)
        self.assertEqual( ledger.natural_balance( ordinary ), Decimal( '100000' ) )

    def test_taxable_windfall_is_taxed_at_year_close( self ):
        # over a full year the ordinary windfall is taxed, so net worth ends below cash + amount
        reader = self._run(
            ScheduledWindfall( date( 2026, 3, 1 ), Decimal( '100000' ), IncomeTaxClass.ORDINARY ),
            end_date = date( 2026, 12, 31 ) )
        net_worth = reader.ledger.net_worth( through = date( 2026, 12, 31 ) )
        self.assertGreater( net_worth, Decimal( '10000' ) )
        self.assertLess( net_worth, Decimal( '110000' ) )


if __name__ == '__main__':
    unittest.main()
