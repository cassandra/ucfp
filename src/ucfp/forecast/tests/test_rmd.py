"""Tests for required minimum distributions (RMDs), forced at the tax-year close.

The engine sizes the RMD on the prior-year-end balance and the owner's age/cohort and the
Forecast/Period forces the shortfall to cash. A cash withdrawal already taken satisfies the
RMD; a Roth conversion does not (it pays no cash), so the distribution is still forced.
Owner A is born 1951 -> 75 in 2026 (RMD age 73, Uniform Lifetime factor 24.6), and a
246,000 balance / 24.6 = a clean 10,000 required distribution.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    ScheduledRealization,
    Subject,
)
from ucfp.tax.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile


def _holding( reader, handle ):
    return reader.chart.account( handle )


class RmdTests( unittest.TestCase ):

    def _run( self, assets, events ):
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1951, 1, 1 ), 'subject-a' ) ],
            assets        = assets,
            events        = events,
        )
        return Bookkeeper( Forecast( parameters ).run().books )

    def test_rmd_is_forced_at_the_required_minimum( self ):
        # nothing withdrawn, so the full 10,000 RMD is forced to cash (taxed ordinary; under
        # the senior standard deduction here, so no tax -- net worth is unchanged).
        reader = self._run(
            assets = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '246000' ), Decimal( '0' ),
                    handle = 'IRA', owner_handle = 'subject-a' ),
            ],
            events = [] )
        ledger = reader.ledger
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY )
        self.assertEqual( ledger.natural_balance( ordinary ), Decimal( '10000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'IRA' ), through = date( 2026, 12, 31 ) ),
            Decimal( '236000' ) )
        self.assertEqual( ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '246000' ) )

    def test_a_cash_withdrawal_satisfies_the_rmd( self ):
        # the owner already withdraws the full 10,000 to cash, so no further distribution is
        # forced -- the IRA falls by 10,000, not 20,000.
        reader = self._run(
            assets = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '246000' ), Decimal( '0' ),
                    handle = 'IRA', owner_handle = 'subject-a' ),
            ],
            events = [ ScheduledRealization( date( 2026, 3, 1 ), 'IRA', Decimal( '10000' ) ) ] )
        ledger = reader.ledger
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY )
        self.assertEqual( ledger.natural_balance( ordinary ), Decimal( '10000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'IRA' ), through = date( 2026, 12, 31 ) ),
            Decimal( '236000' ) )

    def test_a_conversion_does_not_satisfy_the_rmd( self ):
        # the owner converts 10,000 to Roth (no cash distributed), so the RMD is still forced
        # on top: the IRA falls by 20,000, the Roth holds the 10,000 conversion.
        reader = self._run(
            assets = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '246000' ), Decimal( '0' ),
                    handle = 'IRA', owner_handle = 'subject-a' ),
                AssetParameters(
                    'Roth', AssetClass.ROTH, Decimal( '0' ), Decimal( '0' ),
                    handle = 'Roth', owner_handle = 'subject-a' ),
            ],
            events = [ ScheduledRealization( date( 2026, 3, 1 ), 'IRA', Decimal( '10000' ), 'Roth' ) ] )
        ledger = reader.ledger
        self.assertEqual(
            ledger.market_value( _holding( reader, 'IRA' ), through = date( 2026, 12, 31 ) ),
            Decimal( '226000' ) )
        self.assertEqual(
            ledger.market_value( _holding( reader, 'Roth' ), through = date( 2026, 12, 31 ) ),
            Decimal( '10000' ) )


if __name__ == '__main__':
    unittest.main()
