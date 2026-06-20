"""Tests for income resolution in a Forecast (no DB -- the engine is pure domain).

Covers the foundational wiring: per-person income accounts and the today's-dollars ->
nominal COLA growth from the forecast start. Revenue accounts only receive income, so the
assertions are robust to whatever tax/funding posts elsewhere.
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
    AssetParameters,
    ForecastParameters,
    IncomeStream,
    Subject,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus


def _run_two_pension_forecast():
    """Two people with Social Security, a 2% SS COLA, over 2026-2028."""
    alice = Subject( 'Alice', date( 1958, 1, 1 ), 'alice' )
    bob = Subject( 'Bob', date( 1960, 1, 1 ), 'bob' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.MARRIED_JOINT,
        tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
        subjects      = [ alice, bob ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ) ) ],
        economic_outlook = EconomicOutlook.constant(
            EconomicParameters( social_security_cola = Rate( Decimal( '0.02' ) ) ) ),
        income_streams = [
            IncomeStream( alice, IncomeTaxClass.SOCIAL_SECURITY, Decimal( '30000' ) ),
            IncomeStream( bob, IncomeTaxClass.SOCIAL_SECURITY, Decimal( '20000' ) ),
        ],
    )
    return Forecast( parameters ).run()


class IncomeForecastTests( unittest.TestCase ):

    def test_social_security_is_per_person( self ):
        result = _run_two_pension_forecast()
        chart = Bookkeeper( result.books ).chart
        # a distinct Social Security account per subject, found by owner handle
        alice_ss = chart.income_account( IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'alice' )
        bob_ss = chart.income_account( IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'bob' )
        self.assertIsNotNone( alice_ss )
        self.assertIsNotNone( bob_ss )
        self.assertIsNot( alice_ss, bob_ss )

    def test_income_grows_by_cola_from_forecast_start( self ):
        result = _run_two_pension_forecast()
        reader = Bookkeeper( result.books )
        alice_ss = reader.chart.income_account(
            IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'alice' )
        # start year is the base (no growth); then +2% a year, accumulating in the account
        self.assertEqual(
            reader.ledger.natural_balance( alice_ss, through = date( 2026, 12, 31 ) ), Decimal( '30000' ) )
        # 30000 + 30000*1.02 + 30000*1.02^2 = 30000 + 30600 + 31212
        self.assertEqual(
            reader.ledger.natural_balance( alice_ss, through = date( 2028, 12, 31 ) ), Decimal( '91812' ) )


if __name__ == '__main__':
    unittest.main()
