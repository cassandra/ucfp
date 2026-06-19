"""Test that a forecast with taxable income actually settles tax.

The year-close tax step posts charges to per-tax-payment-class expense accounts, which the
Forecast must have created. Before that fix this run raised MissingAccountError; here it
should settle a positive federal income tax.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, IncomeStream, Subject
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus


class TaxSettlementTests( unittest.TestCase ):

    def test_taxable_income_settles_income_tax( self ):
        subject = Subject( 'A', date( 1958, 1, 1 ) )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
            income_streams = [ IncomeStream( subject, IncomeTaxClass.ORDINARY, Decimal( '120000' ) ) ],
        )
        result = Forecast( parameters ).run()   # raised MissingAccountError before the fix
        reader = Bookkeeper( result.books )
        income_tax = next(
            account for account in reader.chart.accounts()
            if account.expense_tax_class == ExpenseTaxClass.INCOME_TAX )
        self.assertGreater( reader.ledger.natural_balance( income_tax ), Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
