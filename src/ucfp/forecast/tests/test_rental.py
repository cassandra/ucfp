"""End-to-end tests for rental real estate: the annual depreciation deduction and the
§1250 depreciation recapture at sale.

The depreciation *amounts* are exactly tested in ucfp.jurisdiction.us.tests.test_depreciation; here we
verify the integration through the Forecast: depreciation shields rental income while held,
and a sale recaptures it. The recapture's effect lands in the income-tax charge (bracket
math, not a book account), so it is verified directionally -- with vs. without an
accumulated-depreciation basis -- while the realize-side facts (the book gain into long-term
gains, the sale mechanics, a balanced ledger) are asserted exactly.

A rental's `cost_basis` is its ORIGINAL purchase price, not its depreciated/adjusted basis:
the book gain is proceeds - cost_basis (the appreciation, into long-term gains), and the
engine adds the depreciation back as §1250 recapture on top -- so passing the adjusted basis
would double-count the depreciation.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    IncomeStream,
    LoanParameters,
    PropertyAttributes,
    ScheduledRealization,
    Subject,
    WindowedAmount,
)
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile


def _income_tax( reader ):
    account = reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX )
    return reader.ledger.natural_balance( account )


class RentalDepreciationDeductionTests( unittest.TestCase ):
    """While a rental is held, depreciation reduces its taxable net income."""

    def _income_tax_with_basis( self, depreciable_basis ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'cash' ),
                AssetParameters(
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '500000' ), Decimal( '500000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2026, 1, 1 ),
                        depreciable_basis = depreciable_basis,
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.GROSS_RENTAL,
                              Schedule.constant( WindowedAmount( Decimal( '60000' ) ) ) ) ],
        )
        return _income_tax( Bookkeeper( Forecast( parameters ).run().books ) )

    def test_depreciation_lowers_tax_while_held( self ):
        # 275000 building basis depreciates 10000/yr, shielding that much rental income
        with_depreciation = self._income_tax_with_basis( Decimal( '275000' ) )
        without = self._income_tax_with_basis( Decimal( '0' ) )
        self.assertLess( with_depreciation, without )


class RentalLoanInterestNettingTests( unittest.TestCase ):
    """A rental mortgage's interest is a Schedule-E rental expense netted against gross rent, not
    itemized home-mortgage interest. Classed RENTAL_EXPENSE it nets dollar-for-dollar against the
    rental income; classed MORTGAGE_INTEREST (Schedule A) it gives a standard-deduction filer no
    benefit -- so the correct classification yields the lower tax."""

    def _income_tax_with_interest_class( self, interest_class ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'cash' ),
                AssetParameters(
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '500000' ), Decimal( '500000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2026, 1, 1 ),
                        depreciable_basis = Decimal( '0' ),               # isolate the interest effect
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.GROSS_RENTAL,
                              Schedule.constant( WindowedAmount( Decimal( '60000' ) ) ) ) ],
            loans = [ LoanParameters(
                'Rental Mortgage', Decimal( '250000' ), Rate( Decimal( '0.05' ) ),
                Duration( 30, TimeUnit.YEAR ), interest_class = interest_class ) ],
        )
        return _income_tax( Bookkeeper( Forecast( parameters ).run().books ) )

    def test_rental_loan_interest_nets_against_rent( self ):
        # The ~12,500 first-year interest nets against the 60k rent as a RENTAL_EXPENSE; as
        # itemized MORTGAGE_INTEREST it is below the single standard deduction, so it does not.
        netted     = self._income_tax_with_interest_class( ExpenseTaxClass.RENTAL_EXPENSE )
        itemizable = self._income_tax_with_interest_class( ExpenseTaxClass.MORTGAGE_INTEREST )
        self.assertLess( netted, itemizable )


class RentalSaleRecaptureTests( unittest.TestCase ):
    """Selling a rental: the appreciation is a long-term gain and the accumulated
    depreciation is recaptured (raising the tax)."""

    def _parameters( self, depreciable_basis ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters(
                    # market 600k now, bought for 400k in 2010 -> 200k appreciation embedded
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '600000' ), Decimal( '400000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2010, 1, 1 ),
                        depreciable_basis = depreciable_basis,
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            events        = [ ScheduledRealization( date( 2026, 1, 1 ), 'rental', Decimal( '600000' ) ) ],
        )

    def test_sale_mechanics_and_book_gain( self ):
        reader = Bookkeeper( Forecast( self._parameters( Decimal( '300000' ) ) ).run().books )
        ledger = reader.ledger
        through = date( 2026, 12, 31 )
        # the rental is emptied; its proceeds land in cash (less the year-end tax)
        self.assertEqual(
            ledger.market_value( reader.chart.account( 'rental' ), through = through ), Decimal( '0' ) )
        # the appreciation (600k - 400k basis) is recognized as a long-term gain
        long_term = reader.chart.income_account( IncomeTaxClass.LONG_TERM_GAINS )
        self.assertEqual( ledger.natural_balance( long_term ), Decimal( '200000' ) )
        reader.assert_balanced()

    def test_recapture_raises_tax_at_sale( self ):
        # identical sales except for the accumulated depreciation; the depreciated rental
        # recaptures it (a §1250 gain), so it owes more tax than the never-depreciated one
        depreciated = _income_tax(
            Bookkeeper( Forecast( self._parameters( Decimal( '300000' ) ) ).run().books ) )
        not_depreciated = _income_tax(
            Bookkeeper( Forecast( self._parameters( Decimal( '0' ) ) ).run().books ) )
        self.assertGreater( depreciated, not_depreciated )


if __name__ == '__main__':
    unittest.main()
