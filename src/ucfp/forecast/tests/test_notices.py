"""Tests for the Notice stream the Forecast surfaces -- the catalog and the memo/link split.

A Notice flags something consequential the user did not directly request: an automatic action
(forced RMD, a funding draw that sold assets) at INFO, or an adverse/constraint outcome
(early-withdrawal penalty, cash shortfall, net-worth depletion) at WARNING. A transactional
notice links to its transaction by `transaction_uuid`; that transaction's `description` memo
carries the per-posting detail, so the notice does not restate it. State notices (shortfall,
depletion) carry no transaction link.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ExpenseItem,
    ForecastParameters,
    ScheduledRealization,
    Subject,
    WindowedAmount,
)
from ucfp.period.results import NoticeKind, NoticeSeverity
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

_PROFILE = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW )


def _notices( result ):
    return [ notice for step in result.steps for notice in step.result.notices ]


def _notice( result, kind ):
    return next( notice for notice in _notices( result ) if notice.kind == kind )


def _transaction( books, transaction_uuid ):
    return next( txn for txn in books.transactions if txn.transaction_uuid == transaction_uuid )


def _expense( name, amount ):
    return ExpenseItem(
        name, ExpenseTaxClass.LIVING, Schedule.constant( WindowedAmount( Decimal( amount ) ) ),
        Recurrence( Duration( 1, TimeUnit.YEAR ) ) )


class NoticeCatalogTests( unittest.TestCase ):

    def test_forced_rmd_raises_an_info_notice_linked_to_its_transaction( self ):
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1951, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '246000' ), Decimal( '0' ),
                    handle = 'ira', owner_handle = 'subject-a' ) ],
        ) ).run()
        notice = _notice( result, NoticeKind.REQUIRED_MINIMUM_DISTRIBUTION )
        self.assertEqual( notice.severity, NoticeSeverity.INFO )
        self.assertEqual( notice.amount, Decimal( '10000' ) )
        # the link resolves to a transaction whose memo carries the detail (not restated here)
        transaction = _transaction( result.books, notice.transaction_uuid )
        self.assertIn( 'Required minimum distribution', transaction.description )

    def test_early_withdrawal_penalty_raises_a_warning_notice_linked_to_its_charge( self ):
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1970, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '40000' ), Decimal( '0' ),
                    handle = 'ira', owner_handle = 'subject-a' ) ],
            events        = [ ScheduledRealization( date( 2026, 3, 1 ), 'ira', Decimal( '40000' ) ) ],
        ) ).run()
        notice = _notice( result, NoticeKind.EARLY_WITHDRAWAL_PENALTY )
        self.assertEqual( notice.severity, NoticeSeverity.WARNING )
        self.assertEqual( notice.amount, Decimal( '4000' ) )
        transaction = _transaction( result.books, notice.transaction_uuid )
        self.assertIn( 'early-withdrawal penalty', transaction.description )

    def test_funding_draw_raises_an_info_notice_linked_to_its_sale( self ):
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '5000' ), Decimal( '5000' ) ),
                AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '500000' ),
                                 Decimal( '500000' ) ) ],
            expenses      = [ _expense( 'Living', '50000' ) ],
            cash_target   = Decimal( '10000' ),
            draw_order    = [ AssetClass.STOCKS ],
        ) ).run()
        notice = _notice( result, NoticeKind.FUNDING_DRAW )
        self.assertEqual( notice.severity, NoticeSeverity.INFO )
        self.assertIsNotNone( _transaction( result.books, notice.transaction_uuid ) )

    def test_funding_draw_from_pretax_under_59_incurs_the_penalty( self ):
        # a waterfall draw from a pre-tax account (NOT a scheduled event) still incurs the
        # early-withdrawal penalty: the penalty reads cash distributions from the books, so it
        # sees the draw however it arose. A 60k expense against 5k cash forces a 65k draw from
        # the IRA up to the 10k target; 10% of that is the penalty.
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1970, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '5000' ), Decimal( '5000' ) ),
                AssetParameters(
                    'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '500000' ), Decimal( '0' ),
                    owner_handle = 'subject-a' ) ],
            expenses      = [ _expense( 'Living', '60000' ) ],
            cash_target   = Decimal( '10000' ),
            draw_order    = [ AssetClass.PRETAX_RETIREMENT ],
        ) ).run()
        penalty = _notice( result, NoticeKind.EARLY_WITHDRAWAL_PENALTY )
        self.assertEqual( penalty.severity, NoticeSeverity.WARNING )
        self.assertEqual( penalty.amount, Decimal( '6500' ) )   # 10% of the 65k forced draw

    def test_cash_shortfall_and_depletion_raise_state_warnings( self ):
        # cash 10k, a 50k expense, no other assets: cash goes negative and net worth depletes
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ) ) ],
            expenses      = [ _expense( 'Living', '50000' ) ],
        ) ).run()
        shortfall = _notice( result, NoticeKind.CASH_SHORTFALL )
        self.assertEqual( shortfall.severity, NoticeSeverity.WARNING )
        self.assertLess( shortfall.amount, Decimal( '0' ) )
        self.assertIsNone( shortfall.transaction_uuid )   # a state notice, no linked posting
        depletion = _notice( result, NoticeKind.NET_WORTH_DEPLETED )
        self.assertEqual( depletion.severity, NoticeSeverity.WARNING )
        self.assertTrue( result.stopped_early )

    def test_scheduled_event_raises_no_notice( self ):
        # a sale the user scheduled is requested, so it gets a memo, not a notice
        result = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 6, 30 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ), 'subject-a' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters( 'Stocks', AssetClass.STOCKS, Decimal( '50000' ), Decimal( '50000' ),
                                 handle = 'stocks' ) ],
            events        = [ ScheduledRealization( date( 2026, 3, 1 ), 'stocks', Decimal( '50000' ) ) ],
        ) ).run()
        self.assertEqual( _notices( result ), [] )


if __name__ == '__main__':
    unittest.main()
