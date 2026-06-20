"""Tests for retirement contributions -- the accrual-phase mirror of withdrawals.

Covers the three sources (wage/personal pre-tax, Roth, employer match), their net-worth and
tax effects, the above-the-line deduction for pre-tax cash contributions, and the key
correctness property: a pre-tax contribution (added to the zero-basis valuation companion) is
taxed in full when later withdrawn -- the contributed principal included.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, SystemAccountRole
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ContributionSource,
    ForecastParameters,
    IncomeStream,
    RetirementContribution,
    ScheduledRealization,
    Subject,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus

_PROFILE = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW )
_SUBJECT = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )   # age 51 in 2026, working


def _holding( reader, handle ):
    return reader.chart.account( handle )


def _income_tax( reader ):
    return reader.ledger.natural_balance(
        reader.chart.expense_account( ExpenseTaxClass.INCOME_TAX ) )


def _parameters( contributions, assets = None, income = Decimal( '120000' ), end = date( 2026, 12, 31 ) ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end,
        filing_status = FilingStatus.SINGLE,
        tax_forecast  = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = assets if assets is not None else [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
            AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                             handle = '401k', owner_handle = 'subject-a' ) ],
        income_streams = [ IncomeStream( _SUBJECT, IncomeTaxClass.WAGES, income ) ],
        contributions = contributions,
    )


class ContributionMechanicsTests( unittest.TestCase ):

    def test_pretax_contribution_grows_the_account_and_lowers_tax( self ):
        with_contrib = Bookkeeper( Forecast( _parameters(
            [ RetirementContribution( '401k', Decimal( '20000' ), ContributionSource.WAGE ) ] ) ).run().books )
        without = Bookkeeper( Forecast( _parameters( [] ) ).run().books )
        # the 401k grows by the contribution
        self.assertEqual(
            with_contrib.ledger.market_value(
                _holding( with_contrib, '401k' ), through = date( 2026, 12, 31 ) ),
            Decimal( '20000' ) )
        # and the pre-tax deduction lowers income tax versus not contributing
        self.assertLess( _income_tax( with_contrib ), _income_tax( without ) )

    def test_employer_match_raises_net_worth_and_is_not_deducted( self ):
        match = Bookkeeper( Forecast( _parameters(
            [ RetirementContribution( '401k', Decimal( '20000' ), ContributionSource.EMPLOYER ) ] ) ).run().books )
        without = Bookkeeper( Forecast( _parameters( [] ) ).run().books )
        # the match builds the 401k from outside money, raising net worth (vs no contribution)
        self.assertEqual(
            match.ledger.market_value( _holding( match, '401k' ), through = date( 2026, 12, 31 ) ),
            Decimal( '20000' ) )
        external = match.chart.system_account( SystemAccountRole.EXTERNAL_RECEIPTS )
        self.assertEqual( match.ledger.natural_balance( external ), Decimal( '20000' ) )
        # a match is not the employee's income, so it is not deducted -- tax is unchanged
        self.assertEqual( _income_tax( match ), _income_tax( without ) )

    def test_roth_contribution_is_not_deducted( self ):
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
            AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '0' ), Decimal( '0' ),
                             handle = 'roth', owner_handle = 'subject-a' ) ]
        roth = Bookkeeper( Forecast( _parameters(
            [ RetirementContribution( 'roth', Decimal( '20000' ), ContributionSource.PERSONAL ) ],
            assets = assets ) ).run().books )
        without = Bookkeeper( Forecast( _parameters( [], assets = assets ) ).run().books )
        self.assertEqual(
            roth.ledger.market_value( _holding( roth, 'roth' ), through = date( 2026, 12, 31 ) ),
            Decimal( '20000' ) )
        # a Roth contribution is after-tax: no deduction
        self.assertEqual( _income_tax( roth ), _income_tax( without ) )

    def test_pretax_contribution_is_taxed_in_full_on_later_withdrawal( self ):
        # the key zero-basis property: contribute 20k pre-tax in 2026, withdraw it in 2027 ->
        # the whole 20k (contributed principal, not just growth) is recognized as ordinary income
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            tax_forecast  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
                AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                                 handle = '401k', owner_handle = 'subject-a' ) ],
            income_streams = [ IncomeStream( _SUBJECT, IncomeTaxClass.WAGES, Decimal( '120000' ) ) ],
            contributions = [
                RetirementContribution(
                    '401k', Decimal( '20000' ), ContributionSource.WAGE,
                    window = DateWindow( end = date( 2026, 12, 31 ) ) ) ],
            events        = [ ScheduledRealization( date( 2027, 6, 1 ), '401k', Decimal( '20000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY )
        # the full 20k withdrawal is ordinary income, not just any growth (there is none here)
        self.assertEqual( reader.ledger.natural_balance( ordinary ), Decimal( '20000' ) )


class ContributionValidationTests( unittest.TestCase ):

    def test_contribution_to_a_non_retirement_holding_is_rejected( self ):
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ),
                             handle = 'brokerage' ) ]
        with self.assertRaises( Exception ):
            Forecast( _parameters(
                [ RetirementContribution( 'brokerage', Decimal( '20000' ), ContributionSource.PERSONAL ) ],
                assets = assets ) ).run()

    def test_employer_match_to_a_roth_is_rejected( self ):
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
            AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '0' ), Decimal( '0' ),
                             handle = 'roth', owner_handle = 'subject-a' ) ]
        with self.assertRaises( ValueError ):
            Forecast( _parameters(
                [ RetirementContribution( 'roth', Decimal( '20000' ), ContributionSource.EMPLOYER ) ],
                assets = assets ) ).run()


if __name__ == '__main__':
    unittest.main()
