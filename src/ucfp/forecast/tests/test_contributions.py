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
from common.rate import Rate
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass, SystemAccountRole
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.tests.tax_helpers import total_income_tax
from ucfp.forecast.parameters import (
    AssetParameters,
    ContributionSource,
    ForecastParameters,
    IncomeStream,
    RetirementContribution,
    ScheduledRealization,
    Subject,
    WindowedAmount,
)
from ucfp.period.results import NoticeKind, NoticeSeverity
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )   # age 51 in 2026, working


def _holding( reader, handle ):
    return reader.chart.account( handle )


def _cap_notices( result ):
    return [ notice for step in result.steps for notice in step.result.notices
             if notice.kind == NoticeKind.CONTRIBUTION_CAPPED ]


def _income_tax( reader ):
    return total_income_tax( reader )


def _parameters( contributions, assets = None, income = Decimal( '120000' ), end = date( 2026, 12, 31 ) ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end,
        filing_status = FilingStatus.SINGLE,
        statute  = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = assets if assets is not None else [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
            AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                             handle = '401k', owner_handle = 'subject-a' ) ],
        income_streams = [ IncomeStream(
            _SUBJECT, IncomeTaxClass.WAGES, Schedule.constant( WindowedAmount( income ) ) ) ],
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
            [ RetirementContribution( 'roth', Decimal( '7000' ), ContributionSource.PERSONAL ) ],
            assets = assets ) ).run().books )
        without = Bookkeeper( Forecast( _parameters( [], assets = assets ) ).run().books )
        self.assertEqual(
            roth.ledger.market_value( _holding( roth, 'roth' ), through = date( 2026, 12, 31 ) ),
            Decimal( '7000' ) )
        # a Roth contribution is after-tax: no deduction
        self.assertEqual( _income_tax( roth ), _income_tax( without ) )

    def test_pretax_contribution_is_taxed_in_full_on_later_withdrawal( self ):
        # the key zero-basis property: contribute 20k pre-tax in 2026, withdraw it in 2027 ->
        # the whole 20k (contributed principal, not just growth) is recognized as ordinary income
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
                AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                                 handle = '401k', owner_handle = 'subject-a' ) ],
            income_streams = [ IncomeStream(
                _SUBJECT, IncomeTaxClass.WAGES,
                Schedule.constant( WindowedAmount( Decimal( '120000' ) ) ) ) ],
            contributions = [
                RetirementContribution(
                    '401k', Decimal( '20000' ), ContributionSource.WAGE,
                    window = DateWindow( end = date( 2026, 12, 31 ) ) ) ],
            events        = [ ScheduledRealization( date( 2027, 6, 1 ), '401k', Decimal( '20000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        distribution = reader.chart.income_account( IncomeTaxClass.RETIREMENT_DISTRIBUTION )
        # the full 20k withdrawal is ordinary income, not just any growth (there is none here)
        self.assertEqual( reader.ledger.natural_balance( distribution ), Decimal( '20000' ) )


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

    def test_first_year_contribution_over_the_limit_is_rejected( self ):
        # 40k deferral exceeds the 31000 catch-up 401(k) limit in the first year -> a planner error
        with self.assertRaises( ValueError ):
            Forecast( _parameters(
                [ RetirementContribution( '401k', Decimal( '40000' ), ContributionSource.WAGE ) ] ) ).run()


class ContributionLimitTests( unittest.TestCase ):

    def _grown_contributions( self, contributions, assets = None ):
        # a two-year forecast with 10%/yr wage growth, so a contribution can grow past its limit
        return Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2027, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = assets if assets is not None else [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ),
                AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                                 handle = '401k', owner_handle = 'subject-a' ) ],
            income_streams   = [ IncomeStream(
                _SUBJECT, IncomeTaxClass.WAGES,
                Schedule.constant( WindowedAmount( Decimal( '200000' ) ) ) ) ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( wage_growth = Rate( Decimal( '0.10' ) ) ) ),
            contributions    = contributions,
        ) ).run()

    def test_catch_up_limit_applies_at_fifty_plus( self ):
        # the subject is 51, so the 401(k) limit is 23500 + 7500 catch-up = 31000; a 30k deferral
        # fits and is contributed in full (the 23500 base alone would clamp it)
        result = Forecast( _parameters(
            [ RetirementContribution( '401k', Decimal( '30000' ), ContributionSource.WAGE ) ] ) ).run()
        reader = Bookkeeper( result.books )
        self.assertEqual(
            reader.ledger.market_value( _holding( reader, '401k' ), through = date( 2026, 12, 31 ) ),
            Decimal( '30000' ) )
        self.assertEqual( _cap_notices( result ), [] )

    def test_contribution_clamped_when_growth_pushes_it_past_the_limit( self ):
        # 30k in 2026 (under the 31000 limit); grown 10% it wants 33k in 2027, clamped to 31000
        result = self._grown_contributions(
            [ RetirementContribution( '401k', Decimal( '30000' ), ContributionSource.WAGE ) ] )
        reader = Bookkeeper( result.books )
        self.assertEqual(
            reader.ledger.market_value( _holding( reader, '401k' ), through = date( 2027, 12, 31 ) ),
            Decimal( '61000' ) )                                   # 30000 + clamped 31000
        caps = _cap_notices( result )
        self.assertEqual( len( caps ), 1 )
        self.assertEqual( caps[ 0 ].amount, Decimal( '2000' ) )    # 33000 wanted - 31000 allowed
        self.assertEqual( caps[ 0 ].severity, NoticeSeverity.WARNING )

    def test_contributions_to_two_accounts_share_one_limit( self ):
        # two 401(k)s for one owner share the single employer-plan limit: 15k + 15k = 30k fits in
        # 2026, but grown 10% it is 33k in 2027 and is clamped to 31000 across both together
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ),
            AssetParameters( '401k-A', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                             handle = '401k-a', owner_handle = 'subject-a' ),
            AssetParameters( '401k-B', AssetClass.PRETAX_RETIREMENT, Decimal( '0' ), Decimal( '0' ),
                             handle = '401k-b', owner_handle = 'subject-a' ) ]
        result = self._grown_contributions(
            [ RetirementContribution( '401k-a', Decimal( '15000' ), ContributionSource.WAGE ),
              RetirementContribution( '401k-b', Decimal( '15000' ), ContributionSource.WAGE ) ],
            assets = assets )
        reader = Bookkeeper( result.books )
        through = date( 2027, 12, 31 )
        combined = (
            reader.ledger.market_value( _holding( reader, '401k-a' ), through = through )
            + reader.ledger.market_value( _holding( reader, '401k-b' ), through = through ) )
        self.assertEqual( combined, Decimal( '61000' ) )          # 30000 + clamped 31000
        self.assertEqual( len( _cap_notices( result ) ), 1 )      # one notice for the shared group


if __name__ == '__main__':
    unittest.main()
