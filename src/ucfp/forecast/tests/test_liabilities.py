"""Tests for liabilities: a loan seeded at t0 and amortized over its term.

Covers the opening balance in net worth, the interest = balance x rate split, and full
amortization to zero by the term (the derived level payment, with the final payment
capped to the remaining balance).
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    LoanParameters,
    Subject,
)
from ucfp.tax.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile


def _parameters( end_date ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end_date,
        filing_status = FilingStatus.MARRIED_JOINT,
        tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
        subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
        loans         = [ LoanParameters(
            'Mortgage', Decimal( '200000' ), Rate( Decimal( '0.05' ) ),
            Duration( 30, TimeUnit.YEAR ), ExpenseTaxClass.MORTGAGE_INTEREST,
            handle = 'mortgage', interest_handle = 'mortgage-interest' ) ],
    )


def _account( reader, handle ):
    return reader.chart.account( handle )


class LiabilityTests( unittest.TestCase ):

    def test_opening_balance_reduces_net_worth( self ):
        reader = Bookkeeper( Forecast( _parameters( date( 2026, 12, 31 ) ) ).run().books )
        # opening (day before the start): $500k cash less the $200k mortgage
        self.assertEqual( reader.ledger.net_worth( through = date( 2025, 12, 31 ) ), Decimal( '300000' ) )

    def test_first_year_interest_is_balance_times_rate( self ):
        reader = Bookkeeper( Forecast( _parameters( date( 2026, 12, 31 ) ) ).run().books )
        self.assertEqual(
            reader.ledger.natural_balance( _account( reader, 'mortgage-interest' ) ), Decimal( '10000' ) )
        self.assertLess(
            reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '200000' ) )

    def test_loan_amortizes_to_zero_by_the_term( self ):
        # run past the 30-year term; the level payment retires the balance, final payment capped
        reader = Bookkeeper( Forecast( _parameters( date( 2060, 12, 31 ) ) ).run().books )
        self.assertEqual( reader.ledger.natural_balance( _account( reader, 'mortgage' ) ), Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
