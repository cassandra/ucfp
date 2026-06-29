"""End-to-end behavior of a mid-year forecast start (issue #17).

A first-of-month mid-year start yields a partial first calendar year. Recurring flows prorate to
it; one-time events land full; and its income tax is the IRC section 443 short-period estimate --
annualize the in-window run-rate, apply full-year brackets, prorate the charge by coverage --
which the Forecast implements by handing the Period an annualizing `EstimatedFiscalWindow`. A
January-1 start is unchanged. These are the subtle behaviors the feature turns on, so they earn a
committed test."""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, OneTime, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, IncomeItem, IncomeStream, Subject, WindowedAmount )
from ucfp.period.results import NoticeKind
from ucfp.jurisdiction.enums import FilingStatus, TaxForecastType, TaxLawType
from ucfp.jurisdiction.law import TaxForecastProfile

_TAX     = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW )
_NULL    = EconomicOutlook.constant( EconomicParameters() )
_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _reader( result ):
    return Bookkeeper( result.books )


class MidYearStartTests( unittest.TestCase ):

    def _result( self, start, end = date( 2027, 12, 31 ), income_items = None, granularity = _MONTHLY ):
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )
        parameters = ForecastParameters(
            start_date    = start,
            end_date      = end,
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _TAX,
            granularity   = granularity,
            subjects      = [ subject ],
            economic_outlook = _NULL,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.WAGES, Schedule.constant( WindowedAmount( Decimal( '120000' ) ) ) ) ],
            income_items  = income_items or [] )
        return Forecast( parameters ).run()

    def _run( self, start, income_items = None ):
        return _reader( self._result( start, income_items = income_items ) )

    def _approximate_years( self, result ):
        return [ step.span.end_date.year for step in result.steps
                 for notice in step.result.notices
                 if notice.kind == NoticeKind.APPROXIMATE_TAX_YEAR ]

    def _flow( self, reader, account, year ):
        return reader.ledger.flows( account, start = date( year, 1, 1 ), end = date( year, 12, 31 ) )

    def _income_tax( self, reader, year ):
        return -self._flow( reader, reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX ), year )

    def test_partial_first_year_income_tax_is_the_short_period_estimate( self ):
        full = self._run( date( 2026, 1, 1 ) )
        partial = self._run( date( 2026, 4, 1 ) )
        full_year_tax = self._income_tax( full, 2027 )
        coverage = Decimal( ( date( 2026, 12, 31 ) - date( 2026, 4, 1 ) ).days + 1 ) / Decimal( '365' )
        # the partial first year is taxed at coverage x the full-year tax (not full brackets on
        # partial income, which the full standard deduction would badly under-tax)
        self.assertAlmostEqual(
            self._income_tax( partial, 2026 ), full_year_tax * coverage, delta = Decimal( '1' ) )
        # less than a full year's tax, but a real positive charge (not the under-taxed naive figure)
        self.assertGreater( self._income_tax( partial, 2026 ), Decimal( '0' ) )
        self.assertLess( self._income_tax( partial, 2026 ), full_year_tax )

    def test_january_start_is_unchanged( self ):
        full = self._run( date( 2026, 1, 1 ) )
        wages = full.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'a' )
        # a full first year books the full run-rate and taxes it as a normal year (to rounding,
        # across the twelve monthly postings)
        self.assertAlmostEqual( self._flow( full, wages, 2026 ), Decimal( '120000' ), delta = Decimal( '0.01' ) )

    def test_partial_first_year_flows_prorate_but_one_time_lands_full( self ):
        bonus = IncomeItem(
            Subject( 'A', date( 1980, 1, 1 ), 'a' ), IncomeTaxClass.ORDINARY,
            Schedule.constant( WindowedAmount( Decimal( '50000' ) ) ), OneTime( date( 2026, 9, 1 ) ) )
        partial = self._run( date( 2026, 4, 1 ), income_items = [ bonus ] )
        wages = partial.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'a' )
        ordinary = partial.chart.income_account( IncomeTaxClass.ORDINARY, owner_handle = 'a' )
        coverage = Decimal( ( date( 2026, 12, 31 ) - date( 2026, 4, 1 ) ).days + 1 ) / Decimal( '365' )
        # the recurring wage stream prorates to the partial year ...
        self.assertAlmostEqual(
            self._flow( partial, wages, 2026 ), Decimal( '120000' ) * coverage, delta = Decimal( '1' ) )
        # ... but the one-time bonus lands at its full amount
        self.assertEqual( self._flow( partial, ordinary, 2026 ), Decimal( '50000' ) )

    def test_partial_first_year_is_flagged_approximate_once( self ):
        result = self._result( date( 2026, 4, 1 ), end = date( 2028, 12, 31 ) )
        # the mid-year first year is flagged once; the full years after it are not
        self.assertEqual( self._approximate_years( result ), [ 2026 ] )

    def test_trailing_partial_year_is_flagged_approximate( self ):
        result = self._result( date( 2026, 1, 1 ), end = date( 2028, 6, 30 ) )
        # a full first year, full middle year, and a trailing partial year (ends June 30)
        self.assertEqual( self._approximate_years( result ), [ 2028 ] )

    def test_full_calendar_forecast_raises_no_approximate_notice( self ):
        result = self._result( date( 2026, 1, 1 ), end = date( 2028, 12, 31 ) )
        self.assertEqual( self._approximate_years( result ), [] )

    def test_partial_first_year_flows_are_granularity_invariant( self ):
        # the partial year's recurring wage total is the same run at annual or monthly
        annual = _reader( self._result(
            date( 2026, 4, 1 ), granularity = Duration( 1, TimeUnit.YEAR ) ) )
        monthly = _reader( self._result( date( 2026, 4, 1 ) ) )
        annual_wages = annual.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'a' )
        monthly_wages = monthly.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'a' )
        self.assertAlmostEqual(
            self._flow( annual, annual_wages, 2026 ),
            self._flow( monthly, monthly_wages, 2026 ), delta = Decimal( '0.01' ) )


if __name__ == '__main__':
    unittest.main()
