"""Sub-quantum residual handling -- regression for a save-time "$0.00 is not greater than zero" crash.

Geometric decay leaves a residual below the money quantum: a loan amortizing off its principal, or a
depreciating vehicle, approaches zero asymptotically without landing on it. Persisted, such a residual
rounds to $0.00 and violates the ledger's strictly-positive amount contract. Two guards prevent it -- a
loan payoff skips a balance that quantizes to zero, and a depreciating holding is written off to exactly
zero once it falls below half a displayed cent.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_span import DateSpan
from common.rate import Rate
from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.period.events import LoanPayoff
from ucfp.period.parameters import AssetRates, FundingPolicy, PeriodParameters
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult

_D = Decimal


class LoanPayoffResidualTests( unittest.TestCase ):

    def _books_with_loan_balance( self, balance ):
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        loan = bookkeeper.add_account(
            Account( name = 'Car loan', parent = chart.root( AccountType.LIABILITY ) ) )
        cash = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        bookkeeper.record( date( 2030, 1, 1 ), [ ( loan, balance ), ( opening, -balance ) ] )
        return bookkeeper, loan, cash

    def test_a_sub_quantum_residual_posts_nothing( self ):
        # A loan amortized down to a raw sub-cent residual must not book a zero-magnitude payoff entry.
        bookkeeper, loan, cash = self._books_with_loan_balance( _D( '0.00000403800303936004639' ) )
        before = len( bookkeeper.books.transactions )
        self.assertIsNone( LoanPayoff( date( 2030, 6, 1 ), loan, cash ).apply( bookkeeper ) )
        self.assertEqual( len( bookkeeper.books.transactions ), before )

    def test_a_real_balance_is_still_paid_off( self ):
        bookkeeper, loan, cash = self._books_with_loan_balance( _D( '1234.56' ) )
        self.assertIsNotNone( LoanPayoff( date( 2030, 6, 1 ), loan, cash ).apply( bookkeeper ) )
        self.assertEqual( bookkeeper.ledger.natural_balance( loan ), _D( '0' ) )


class DepreciationWriteOffTests( unittest.TestCase ):

    def _value_after_one_period( self, opening_value ):
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        vehicle = bookkeeper.create_holding(
            chart.root( AccountType.ASSET ), 'Car', AssetClass.DEPRECIATING )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        bookkeeper.record( date( 2029, 12, 31 ), [ ( vehicle, -opening_value ), ( opening, opening_value ) ] )
        parameters = PeriodParameters(
            date_span      = DateSpan( date( 2030, 1, 1 ), date( 2030, 12, 31 ) ),
            tax_context    = TaxContext( FilingStatus.SINGLE ),
            asset_rates    = AssetRates( growth = { AssetClass.DEPRECIATING: Rate( _D( '-0.18' ) ) } ),
            funding_policy = FundingPolicy() )
        Period( parameters )._apply_growth( bookkeeper, PeriodResult() )
        bookkeeper.assert_balanced()
        return bookkeeper.ledger.market_value( vehicle )

    def test_below_half_a_cent_is_written_off_to_exactly_zero( self ):
        self.assertEqual( self._value_after_one_period( _D( '0.003' ) ), _D( '0' ) )

    def test_above_the_floor_depreciates_normally( self ):
        # 0.01 - 18% = 0.0082; the write-off floor leaves a still-visible value alone.
        self.assertEqual( self._value_after_one_period( _D( '0.01' ) ), _D( '0.0082' ) )


if __name__ == '__main__':
    unittest.main()
