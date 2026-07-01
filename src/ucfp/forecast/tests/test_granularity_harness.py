"""Smoke test for the granularity harness itself -- that it runs every granularity and
extracts aligned year-by-year figures. The invariance assertions it enables live in
`test_granularity_invariance.py`; this only checks the machinery works."""
import unittest
from datetime import date
from decimal import Decimal

from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, IncomeStream, Subject, WindowedAmount )
from ucfp.forecast.tests.granularity_harness import GRANULARITIES, compare, render
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


class GranularityHarnessSmokeTest( unittest.TestCase ):

    def _params( self ):
        subject = Subject( 'A', date( 1980, 1, 1 ), 'a' )
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2030, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = _PROFILE,
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ) ],
            income_streams = [ IncomeStream(
                subject, IncomeTaxClass.WAGES,
                Schedule.constant( WindowedAmount( Decimal( '80000' ) ) ) ) ],
        )

    def test_compare_runs_every_granularity_and_extracts_aligned_years( self ):
        comparison = compare( self._params() )
        self.assertEqual( set( comparison ), { name for name, _ in GRANULARITIES } )
        for _name, ( year_list, run_outcome ) in comparison.items():
            self.assertEqual( [ figures.year for figures in year_list ], list( range( 2026, 2031 ) ) )
            self.assertIsNone( run_outcome.depletion_year )           # wages > 0, no depletion
            self.assertGreater( run_outcome.terminal_net_worth, Decimal( '0' ) )

    def test_render_produces_a_report( self ):
        report = render( compare( self._params() ) )
        self.assertIn( 'net_worth', report )
        self.assertIn( 'terminal_net_worth', report )
