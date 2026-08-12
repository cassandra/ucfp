"""_run_outcome: the results page's headline figures -- the projection's year span and the net worth at
the horizon, computed live from the already-loaded books (never cached, the books stay the source of truth
for book-derived figures).
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.recurrence import Duration, TimeUnit
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, Subject
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.planning.materialization import ForecastFrame
from ucfp.planning.views import _run_outcome

_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


class RunOutcomeTests( unittest.TestCase ):

    def test_reports_the_span_and_the_horizon_net_worth_from_the_books( self ):
        # Cash only, no growth/income/expenses: net worth holds at the opening $500,000 through a 3-year
        # horizon, so the outcome is exact.
        frame  = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2028, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date    = frame.start_date,
            end_date      = frame.end_date,
            filing_status = FilingStatus.SINGLE,
            statute       = _STATUTE,
            subjects      = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets        = [ AssetParameters(
                'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
        books = Forecast( params ).run().books

        outcome = _run_outcome( SimpleNamespace( frame = frame ), books )

        self.assertEqual( outcome, {
            'horizon_start': 2026, 'horizon_end': 2028, 'horizon_years': 3,
            'ending_net_worth': Decimal( '500000' ) } )


if __name__ == '__main__':
    unittest.main()
