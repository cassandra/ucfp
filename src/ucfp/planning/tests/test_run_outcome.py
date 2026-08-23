"""run_outcome: the run's shared headline outcome -- the salient result and the start→end arc (year,
household ages, net worth), computed live from the already-loaded books (never cached, the books stay the
source of truth for book-derived figures). A run that stopped early ends at its last computed period, and a
depleted plan's ending net worth is hidden (the result line already conveys it).
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.recurrence import Duration, TimeUnit
from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, Subject
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.planning.materialization import ForecastFrame
from ucfp.planning.overview import run_outcome

_D      = Decimal
_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )


def _run( frame, *, stopped_early, end_date, is_depleted, birthdate = date( 1960, 1, 1 ) ):
    """A minimal ProjectionRun stand-in for `run_outcome`: its frame, the summarized result (one final
    step carrying the stop year and depletion flag), and a single-subject profile for the ages."""
    return SimpleNamespace(
        frame   = frame,
        result  = SimpleNamespace(
            stopped_early = stopped_early,
            steps = [ SimpleNamespace( end_date = end_date, is_depleted = is_depleted ) ] ),
        profile = SimpleNamespace( subjects = [ SimpleNamespace( birthdate = birthdate ) ] ) )


class RunOutcomeTests( unittest.TestCase ):

    def test_a_solvent_run_reports_the_full_arc( self ):
        # Cash only, no growth/income/expenses: net worth holds at the opening $500,000 through a 3-year
        # horizon, so the arc is exact. Subject born 1960 -> age 66 at 2026, 68 at 2028.
        frame  = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2028, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date = frame.start_date, end_date = frame.end_date, filing_status = FilingStatus.SINGLE,
            statute = _STATUTE, subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
        books = Forecast( params ).run().books

        outcome = run_outcome(
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False ), books )

        self.assertEqual( outcome[ 'summary' ], {
            'lasted': True, 'depleted': False, 'years': 3,
            'start': { 'year': 2026, 'ages': 'age 66', 'net_worth': _D( '500000' ) },
            'end': { 'year': 2028, 'ages': 'age 68', 'net_worth': _D( '500000' ), 'has_net_worth': True } } )

    def test_ages_track_the_dates_not_just_the_year( self ):
        # Born Dec 22 1990; a run from Aug to Dec 2026 -> 35 at the start (birthday not yet reached in
        # August), 36 at the end (past the December birthday). A year-only age would show 36 for both.
        frame  = ForecastFrame(
            start_date = date( 2026, 8, 1 ), end_date = date( 2026, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date = frame.start_date, end_date = frame.end_date, filing_status = FilingStatus.SINGLE,
            statute = _STATUTE, subjects = [ Subject( 'you', date( 1990, 12, 22 ) ) ],
            assets = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '100000' ), _D( '100000' ) ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
        books = Forecast( params ).run().books

        outcome = run_outcome(
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False,
                  birthdate = date( 1990, 12, 22 ) ), books )

        self.assertEqual( outcome[ 'summary' ][ 'start' ][ 'ages' ], 'age 35' )
        self.assertEqual( outcome[ 'summary' ][ 'end' ][ 'ages' ], 'age 36' )

    def test_a_depleted_run_ends_at_the_stop_year_and_hides_net_worth( self ):
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2060, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        cash = bookkeeper.create_holding( chart.root( AccountType.ASSET ), 'Cash', AssetClass.CASH )
        loan = bookkeeper.add_account( Account( name = 'Loan', parent = chart.root( AccountType.LIABILITY ) ) )
        opening = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        bookkeeper.record( date( 2026, 1, 1 ), [ ( cash, -_D( '10000' ) ), ( opening, _D( '10000' ) ) ] )
        bookkeeper.record( date( 2026, 1, 1 ), [ ( loan, _D( '50000' ) ), ( opening, -_D( '50000' ) ) ] )

        outcome = run_outcome(
            _run( frame, stopped_early = True, end_date = date( 2032, 12, 31 ), is_depleted = True ),
            bookkeeper.books )

        summary = outcome[ 'summary' ]
        self.assertFalse( summary[ 'lasted' ] )
        self.assertTrue( summary[ 'depleted' ] )
        self.assertEqual( summary[ 'years' ], 7 )                    # ran out 2026..2032
        self.assertEqual( summary[ 'end' ][ 'year' ], 2032 )
        self.assertFalse( summary[ 'end' ][ 'has_net_worth' ] )     # net worth is negative -> hidden


if __name__ == '__main__':
    unittest.main()
