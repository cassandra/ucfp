"""Tests for the external equity events -- value crossing the household boundary that is neither
income nor expense.

A `ScheduledExternalReceipt` is a non-taxable inflow (a gift, a US inheritance): it raises cash
and net worth and credits the External Receipts equity account, untouched by tax. A
`ScheduledExternalDisbursement` is its mirror -- a non-deductible gift given away: it lowers cash
and net worth and debits the External Disbursements equity account, with no expense recognized.
(Taxable one-time income is a one-time `IncomeItem`, covered in test_income; a deductible
charitable gift is a CHARITABLE expense.)
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, SystemAccountRole
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    ScheduledExternalDisbursement,
    ScheduledExternalReceipt,
    Subject,
)
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile


def _holding( reader, handle ):
    return reader.chart.account( handle )


class ExternalFlowTests( unittest.TestCase ):

    def _run( self, event ):
        # a half-year horizon (no year close) isolates the equity event from any tax settlement
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 6, 30 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1960, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'cash' ) ],
            events        = [ event ],
        )
        return Bookkeeper( Forecast( parameters ).run().books )

    def test_external_receipt_credits_equity_and_raises_cash( self ):
        reader = self._run( ScheduledExternalReceipt( date( 2026, 3, 1 ), Decimal( '40000' ) ) )
        ledger = reader.ledger
        through = date( 2026, 6, 30 )
        external = reader.chart.system_account( SystemAccountRole.EXTERNAL_RECEIPTS )
        # cash rises by the receipt; the balancing credit lands in External Receipts equity
        self.assertEqual(
            ledger.market_value( _holding( reader, 'cash' ), through = through ), Decimal( '140000' ) )
        self.assertEqual( ledger.natural_balance( external ), Decimal( '40000' ) )
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '140000' ) )

    def test_external_disbursement_debits_equity_and_lowers_cash( self ):
        reader = self._run( ScheduledExternalDisbursement( date( 2026, 3, 1 ), Decimal( '40000' ) ) )
        ledger = reader.ledger
        through = date( 2026, 6, 30 )
        external = reader.chart.system_account( SystemAccountRole.EXTERNAL_DISBURSEMENTS )
        # cash falls by the gift; the balancing debit lands in External Disbursements equity, so
        # net worth drops by the amount with no expense recognized
        self.assertEqual(
            ledger.market_value( _holding( reader, 'cash' ), through = through ), Decimal( '60000' ) )
        self.assertEqual( ledger.natural_balance( external ), Decimal( '-40000' ) )
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '60000' ) )


if __name__ == '__main__':
    unittest.main()
