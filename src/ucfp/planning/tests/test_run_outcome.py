"""run_outcome: the run's shared headline outcome -- the salient result and the start→end arc (year,
household ages, net worth), computed live from the already-loaded books (never cached, the books stay the
source of truth for book-derived figures). A run that stopped early ends at its last computed period, and a
depleted plan's ending net worth is hidden (the result line already conveys it).
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.rate import Rate
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


def _run( frame, *, stopped_early, end_date, is_depleted, birthdate = date( 1960, 1, 1 ),
          birthdates = None, inflation = _D( '0' ) ):
    """A minimal ProjectionRun stand-in for `run_outcome`: its frame, the summarized result (one final
    step carrying the stop year and depletion flag), a profile of one or more subjects for the ages
    (`birthdates` for a couple, else the single `birthdate`), and an assumptions set carrying the general
    inflation rate (for the today's-dollars restatement)."""
    subjects = [ SimpleNamespace( birthdate = b ) for b in ( birthdates or [ birthdate ] ) ]
    return SimpleNamespace(
        frame       = frame,
        result      = SimpleNamespace(
            stopped_early = stopped_early,
            steps = [ SimpleNamespace(
                start_date = frame.start_date, end_date = end_date, is_depleted = is_depleted ) ] ),
        profile     = SimpleNamespace( subjects = subjects ),
        assumptions = SimpleNamespace( economics = SimpleNamespace( inflation = Rate( inflation ) ) ) )


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
            'lasted': True, 'depleted': False, 'years': 3, 'age_noun': 'Age',   # one subject -> singular
            'start': { 'year': 2026, 'ages': '66', 'net_worth': _D( '500000' ) },
            'end': { 'year': 2028, 'ages': '68', 'net_worth': _D( '500000' ), 'has_net_worth': True,
                     'net_worth_today': None } } )   # zero inflation -> no separate today's-dollars figure

    def test_the_starting_net_worth_excludes_the_first_periods_growth( self ):
        # The engine books a period's growth at the period-START date, so reading the start figure at
        # frame.start_date would fold the first year's appreciation into the "starting" net worth. It must
        # read the opening instant -- the day before the first period -- matching the books table's opening
        # row and the chart's first point. $500,000 of stocks growing 5%/yr: start stays $500,000 while the
        # end has grown.
        frame  = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2027, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date = frame.start_date, end_date = frame.end_date, filing_status = FilingStatus.SINGLE,
            statute = _STATUTE, subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets = [ AssetParameters( 'Stocks', AssetClass.STOCKS, _D( '500000' ), _D( '500000' ) ) ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( stock_appreciation = Rate( _D( '0.05' ) ) ) ) )
        books = Forecast( params ).run().books

        summary = run_outcome(
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False ),
            books )[ 'summary' ]

        self.assertEqual( summary[ 'start' ][ 'net_worth' ], _D( '500000' ) )   # the opening, not $525,000
        self.assertGreater( summary[ 'end' ][ 'net_worth' ], _D( '500000' ) )   # growth did happen

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

        self.assertEqual( outcome[ 'summary' ][ 'start' ][ 'ages' ], '35' )
        self.assertEqual( outcome[ 'summary' ][ 'end' ][ 'ages' ], '36' )

    def test_a_couple_reads_a_plural_age_heading_and_joined_ages( self ):
        # Two subjects -> the ages column heads 'Ages' and each cell joins both members' ages. Net worth
        # is independent of the profile, so a plain cash books suffices.
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
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False,
                  birthdates = [ date( 1960, 1, 1 ), date( 1962, 1, 1 ) ] ), books )

        self.assertEqual( outcome[ 'summary' ][ 'age_noun' ], 'Ages' )
        self.assertEqual( outcome[ 'summary' ][ 'start' ][ 'ages' ], '66 & 64' )

    def test_ending_net_worth_is_restated_in_todays_dollars_by_the_inflation_rate( self ):
        # Cash held flat at $500,000 over a 10-year horizon under 3.5% inflation. The nominal ending
        # figure is unchanged, but the today's-dollars companion discounts it by (1.035 ** 10).
        frame  = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2036, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date = frame.start_date, end_date = frame.end_date, filing_status = FilingStatus.SINGLE,
            statute = _STATUTE, subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
        books = Forecast( params ).run().books

        end = run_outcome(
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False,
                  inflation = _D( '0.035' ) ), books )[ 'summary' ][ 'end' ]

        self.assertEqual( end[ 'net_worth' ], _D( '500000' ) )                 # nominal is unchanged
        self.assertEqual( end[ 'net_worth_today' ], _D( '500000' ) / ( _D( '1.035' ) ** 10 ) )
        self.assertLess( end[ 'net_worth_today' ], _D( '500000' ) )            # today's dollars are fewer

    def test_a_same_year_horizon_has_no_todays_dollars_figure( self ):
        # Start and end land in the same year, so there is nothing to discount even with inflation set.
        frame  = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2026, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        params = ForecastParameters(
            start_date = frame.start_date, end_date = frame.end_date, filing_status = FilingStatus.SINGLE,
            statute = _STATUTE, subjects = [ Subject( 'you', date( 1960, 1, 1 ) ) ],
            assets = [ AssetParameters( 'Cash', AssetClass.CASH, _D( '500000' ), _D( '500000' ) ) ],
            economic_outlook = EconomicOutlook.constant( EconomicParameters() ) )
        books = Forecast( params ).run().books

        end = run_outcome(
            _run( frame, stopped_early = False, end_date = frame.end_date, is_depleted = False,
                  inflation = _D( '0.035' ) ), books )[ 'summary' ][ 'end' ]

        self.assertIsNone( end[ 'net_worth_today' ] )

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
