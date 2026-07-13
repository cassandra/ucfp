"""End-to-end behavior of a mid-year forecast start (issue #17).

A first-of-month mid-year start yields a partial first calendar year. Recurring flows prorate to
it and one-time events land full, exactly as in a full year -- but tax is assessed on whole
calendar years only, so a partial year (the mid-year first year, or a trailing year short of
December 31) is posted yet left untaxed; the Forecast effects that by handing those periods no tax
engine. A January-1 start is a full first year, taxed normally. These are the subtle behaviors the
feature turns on, so they earn a committed test."""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, OneTime, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.tests.tax_helpers import income_tax_accounts
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, IncomeItem, IncomeStream, ScheduledRealization, Subject,
    WindowedAmount )
from ucfp.period.results import NoticeKind, NoticeSeverity
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.jurisdiction.us.state import CapitalLossCarryover, TaxState

_TAX     = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
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
            statute  = _TAX,
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

    def _untaxed_partial_years( self, result ):
        return [ step.span.end_date.year for step in result.steps
                 for notice in step.result.notices
                 if notice.kind == NoticeKind.PARTIAL_YEAR_UNTAXED ]

    def _partial_year_notices( self, result ):
        return [ notice for step in result.steps for notice in step.result.notices
                 if notice.kind == NoticeKind.PARTIAL_YEAR_UNTAXED ]

    def _flow( self, reader, account, year ):
        return reader.ledger.flows( account, start = date( year, 1, 1 ), end = date( year, 12, 31 ) )

    def _income_tax( self, reader, year ):
        return -sum( ( self._flow( reader, account, year )
                       for account in income_tax_accounts( reader.chart ) ), Decimal( '0' ) )

    def test_partial_first_year_is_untaxed_but_full_years_are_taxed( self ):
        full = self._run( date( 2026, 1, 1 ) )
        partial = self._run( date( 2026, 4, 1 ) )
        # tax is assessed on whole calendar years only: a mid-year start makes 2026 partial, so it
        # carries no tax charge at all (rather than the old section-443 short-period estimate)
        self.assertEqual( self._income_tax( partial, 2026 ), Decimal( '0' ) )
        # the full year after it is taxed, and identically to a full-calendar run -- an untaxed
        # partial first year does not perturb the later full years
        self.assertGreater( self._income_tax( partial, 2027 ), Decimal( '0' ) )
        self.assertAlmostEqual(
            self._income_tax( partial, 2027 ), self._income_tax( full, 2027 ), delta = Decimal( '1' ) )

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

    def test_partial_first_year_is_flagged_untaxed_once( self ):
        result = self._result( date( 2026, 4, 1 ), end = date( 2028, 12, 31 ) )
        # the mid-year first year is flagged once; the full years after it are not
        self.assertEqual( self._untaxed_partial_years( result ), [ 2026 ] )
        # its untaxed wages make it a WARNING carrying the approximate untaxed (ordinary) income
        notice = self._partial_year_notices( result )[ 0 ]
        self.assertEqual( notice.severity, NoticeSeverity.WARNING )
        self.assertGreater( notice.amount, Decimal( '0' ) )
        self.assertEqual( notice.detail, 'in approximate untaxed ordinary income' )

    def test_partial_first_year_with_a_sale_warns_and_names_the_untaxed_gain( self ):
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 4, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _TAX,
            granularity   = _MONTHLY,
            subjects      = [ subject ],
            economic_outlook = _NULL,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ),
                AssetParameters(
                    'Stock', AssetClass.STOCKS, Decimal( '300000' ), Decimal( '0' ), handle = 'Stock' ) ],
            events        = [ ScheduledRealization( date( 2026, 9, 1 ), 'Stock', Decimal( '300000' ) ) ] )
        result = Forecast( parameters ).run()
        # the sale realizes a 300000 long-term gain inside the untaxed 2026 stub: the notice becomes
        # a WARNING that names the gain that escaped tax, rather than silently overstating net worth
        self.assertEqual( self._untaxed_partial_years( result ), [ 2026 ] )
        notice = self._partial_year_notices( result )[ 0 ]
        self.assertEqual( notice.severity, NoticeSeverity.WARNING )
        self.assertAlmostEqual( notice.amount, Decimal( '300000' ), delta = Decimal( '1' ) )
        # the amount is labelled so it is not a context-free figure on the run page (gains only here)
        self.assertEqual( notice.detail, 'in approximate untaxed capital gains' )

    def test_partial_year_names_both_capital_gain_and_ordinary_income( self ):
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 4, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _TAX,
            granularity   = _MONTHLY,
            subjects      = [ subject ],
            economic_outlook = _NULL,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ),
                AssetParameters(
                    'Stock', AssetClass.STOCKS, Decimal( '300000' ), Decimal( '0' ), handle = 'Stock' ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.WAGES,
                              Schedule.constant( WindowedAmount( Decimal( '120000' ) ) ) ) ],
            events        = [ ScheduledRealization( date( 2026, 9, 1 ), 'Stock', Decimal( '300000' ) ) ] )
        result = Forecast( parameters ).run()
        notice = self._partial_year_notices( result )[ 0 ]
        # a realized gain and untaxed wages both present: the total is the sum, and the label breaks
        # it down so the user can see how to compensate
        self.assertEqual( notice.severity, NoticeSeverity.WARNING )
        self.assertGreater( notice.amount, Decimal( '380000' ) )   # 300000 gain + ~90000 wages
        self.assertIn( 'approximate untaxed income', notice.detail )
        self.assertRegex( notice.detail, r'capital gains.*ordinary' )

    def test_capital_loss_carryover_survives_an_untaxed_partial_first_year( self ):
        # a prior-year capital-loss carryover threaded in must pass through the untaxed mid-year
        # stub unchanged (it settles no tax, so it neither consumes nor drops the carryforward) and
        # still offset a gain realized in the first full year
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )

        def run( opening_state ):
            parameters = ForecastParameters(
                start_date    = date( 2026, 4, 1 ),
                end_date      = date( 2027, 12, 31 ),
                filing_status = FilingStatus.SINGLE,
                statute       = _TAX,
                granularity   = _MONTHLY,
                subjects      = [ subject ],
                economic_outlook = _NULL,
                assets        = [
                    AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ),
                    AssetParameters(
                        'Stock', AssetClass.STOCKS, Decimal( '200000' ), Decimal( '0' ), handle = 'Stock' ) ],
                events        = [ ScheduledRealization( date( 2027, 3, 1 ), 'Stock', Decimal( '200000' ) ) ],
                initial_tax_state = opening_state )
            return _reader( Forecast( parameters ).run() )
        carried = TaxState( capital_loss_carryover = CapitalLossCarryover( long = Decimal( '50000' ) ) )
        with_loss = run( carried )
        without   = run( None )
        # the gain lands in the full 2027 year and is taxed; the carryforward that survived the
        # untaxed 2026 stub lowers that tax versus starting fresh
        self.assertGreater( self._income_tax( without, 2027 ), Decimal( '0' ) )
        self.assertLess( self._income_tax( with_loss, 2027 ), self._income_tax( without, 2027 ) )

    def test_partial_year_with_no_taxable_income_is_informational( self ):
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 4, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _TAX,
            granularity   = _MONTHLY,
            subjects      = [ subject ],
            economic_outlook = _NULL,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ) ] )
        result = Forecast( parameters ).run()
        # a partial year with nothing readily-taxable is still flagged, but only informationally
        notice = self._partial_year_notices( result )[ 0 ]
        self.assertEqual( notice.severity, NoticeSeverity.INFO )
        self.assertIsNone( notice.amount )

    def test_trailing_partial_year_is_flagged_untaxed( self ):
        result = self._result( date( 2026, 1, 1 ), end = date( 2028, 6, 30 ) )
        # a full first year, full middle year, and a trailing partial year (ends June 30)
        self.assertEqual( self._untaxed_partial_years( result ), [ 2028 ] )
        # a trailing stub carries its untaxed income the same way a leading stub does (here the
        # half-year of wages), not just a bare flag
        notice = self._partial_year_notices( result )[ 0 ]
        self.assertEqual( notice.severity, NoticeSeverity.WARNING )
        self.assertGreater( notice.amount, Decimal( '0' ) )
        self.assertEqual( notice.detail, 'in approximate untaxed ordinary income' )

    def test_full_calendar_forecast_raises_no_partial_year_notice( self ):
        result = self._result( date( 2026, 1, 1 ), end = date( 2028, 12, 31 ) )
        self.assertEqual( self._untaxed_partial_years( result ), [] )

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
