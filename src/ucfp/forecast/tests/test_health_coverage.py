"""Test that subsidized health coverage produces a premium tax credit at the year close.

The household enrolls in subsidized marketplace coverage; the US engine reads the resolved
enrollment and credits the ACA premium tax credit against income tax. A modest ordinary
income keeps the household well within the subsidy range, so the credit is the dominant tax
effect (it offsets income tax, leaving a net refund booked to the income-tax account).
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    IncomeStream,
    SubsidizedHealthCoverage,
    Subject,
    WindowedAmount,
)
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile


class HealthCoverageTests( unittest.TestCase ):

    def _run( self, health_coverage ):
        subject = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ) ],
            income_streams = [ IncomeStream(
                subject, IncomeTaxClass.ORDINARY,
                Schedule.constant( WindowedAmount( Decimal( '40000' ) ) ) ) ],
            health_coverage = health_coverage,
        )
        return Bookkeeper( Forecast( parameters ).run().books )

    def test_enrollment_yields_a_premium_tax_credit( self ):
        # benchmark premium well above the expected contribution -> a positive PTC, which as a
        # refundable credit drives the income-tax account negative (a net refund).
        reader = self._run(
            SubsidizedHealthCoverage(
                window            = DateWindow(),
                household_size    = 1,
                reference_premium = Decimal( '8000' ) ) )
        income_tax = reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX )
        self.assertLess( reader.ledger.natural_balance( income_tax ), Decimal( '0' ) )

    def test_no_coverage_yields_no_credit( self ):
        # without coverage the credit never fires, so income tax is non-negative
        reader = self._run( None )
        income_tax = reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX )
        self.assertGreaterEqual( reader.ledger.natural_balance( income_tax ), Decimal( '0' ) )

    def test_credit_only_within_the_coverage_window( self ):
        # coverage windowed to a later year: this year is uncovered, so no credit
        reader = self._run(
            SubsidizedHealthCoverage(
                window            = DateWindow( start = date( 2030, 1, 1 ) ),
                household_size    = 1,
                reference_premium = Decimal( '8000' ) ) )
        income_tax = reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX )
        self.assertGreaterEqual( reader.ledger.natural_balance( income_tax ), Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
