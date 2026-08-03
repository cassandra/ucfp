"""Metamorphic tests: rather than pin an absolute value (which needs a hand-computed oracle), assert the
*relationship* between two runs that differ by a single input -- directly answering the "what happens
when I change this knob" questions. The short single-knob checks run in the dev gate; the whole-profile,
multi-year comparisons are tagged 'e2e'."""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.test import tag

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetAllocation,
    AssetParameters,
    CashAccountParameters,
    ExpenseStream,
    ForecastParameters,
    LoanParameters,
    Subject,
    WindowedAmount,
)
from ucfp.forecast.tests.granularity_harness import outcome, total_lifetime_tax, yearly_figures
from ucfp.forecast.tests.granularity_profiles import PROFILES, full_tier
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, StatuteProjection, TaxProjection

_D       = Decimal
_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1970, 1, 1 ), 'subject-a' )


def _total_expense_of_class( result, params, expense_class ):
    return sum( ( figures.expense.get( expense_class, _D( '0' ) )
                  for figures in yearly_figures( result, params ) ), _D( '0' ) )


class ExpenseInflationMetamorphicTests( unittest.TestCase ):

    def _living_expense_at_inflation( self, inflation ):
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2030, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '1000000' ), _D( '1000000' ) ) ],
            expense_streams  = [ ExpenseStream(
                'Living', ExpenseTaxClass.LIVING, Schedule.constant( WindowedAmount( _D( '50000' ) ) ) ) ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( inflation = Rate( _D( inflation ) ) ) ),
        )
        return _total_expense_of_class( Forecast( params ).run(), params, ExpenseTaxClass.LIVING )

    def test_higher_inflation_raises_cumulative_living_expense( self ):
        self.assertGreater(
            self._living_expense_at_inflation( '0.05' ), self._living_expense_at_inflation( '0' ) )


class LoanPrepaymentMetamorphicTests( unittest.TestCase ):

    def _total_interest_with_extra( self, annual_extra ):
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2031, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ) ],
            loans         = [ LoanParameters(
                'Mortgage', _D( '200000' ), Rate( _D( '0.05' ) ), Duration( 30, TimeUnit.YEAR ),
                interest_class = ExpenseTaxClass.MORTGAGE_INTEREST,
                annual_extra_principal = _D( annual_extra ) ) ],
        )
        return _total_expense_of_class( Forecast( params ).run(), params, ExpenseTaxClass.MORTGAGE_INTEREST )

    def test_extra_principal_lowers_total_interest_paid( self ):
        self.assertLess(
            self._total_interest_with_extra( '24000' ), self._total_interest_with_extra( '0' ) )


class CashSweepMetamorphicTests( unittest.TestCase ):

    def _swept_into_brokerage( self, ceiling ):
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, _D( '200000' ), _D( '200000' ) ),
                AssetParameters(
                    'Brokerage', AssetClass.STOCKS, _D( '0' ), _D( '0' ), handle = 'brokerage' ) ],
            cash_account  = CashAccountParameters(
                cash_ceiling = _D( ceiling ),
                sweep_allocation = AssetAllocation( ( ( 'brokerage', _D( '1' ) ), ) ) ),
        )
        reader    = Bookkeeper( Forecast( params ).run().books )
        brokerage = reader.chart.account( 'brokerage' )
        return reader.ledger.market_value( brokerage, through = date( 2026, 12, 31 ) )

    def test_a_lower_ceiling_sweeps_more_into_the_brokerage( self ):
        self.assertGreater( self._swept_into_brokerage( '50000' ), self._swept_into_brokerage( '100000' ) )


@tag( 'e2e' )
class StatuteProjectionMetamorphicTests( unittest.TestCase ):

    def _lifetime_tax_under( self, projection ):
        params = replace(
            full_tier( PROFILES[ 'wage_earner' ]() ),
            statute = StatuteProfile( JurisdictionType.US_FEDERAL, projection ) )
        return total_lifetime_tax( Forecast( params ).run(), params )

    def test_cola_indexing_lowers_lifetime_tax_versus_frozen_brackets( self ):
        # Frozen brackets let nominal wage growth creep into higher brackets; indexing the brackets at
        # 3% keeps pace, so the same household owes less over the horizon.
        frozen  = self._lifetime_tax_under( TaxProjection( StatuteForecastType.CURRENT_LAW ) )
        indexed = self._lifetime_tax_under( TaxProjection(
            StatuteForecastType.COLA_INDEXED, StatuteProjection( Rate( _D( '0.03' ) ) ) ) )
        self.assertLess( indexed, frozen )


@tag( 'e2e' )
class AssetGrowthMetamorphicTests( unittest.TestCase ):

    def _terminal_at_stock_appreciation( self, rate ):
        params = replace(
            full_tier( PROFILES[ 'wage_earner' ]() ),
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( stock_appreciation = Rate( _D( rate ) ) ) ) )
        return outcome( Forecast( params ).run(), params ).terminal_net_worth

    def test_higher_stock_appreciation_raises_terminal_net_worth( self ):
        self.assertGreater(
            self._terminal_at_stock_appreciation( '0.08' ), self._terminal_at_stock_appreciation( '0.02' ) )


if __name__ == '__main__':
    unittest.main()
