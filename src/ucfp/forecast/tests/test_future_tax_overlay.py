"""Engine behavior for the Estimated Future Taxes overlay (#177 phase 2): the forecast books it at t0
and each period close, it reduces net worth by exactly the latent tax on current balances, it is inert
at the default zero rates, and it holds across granularities. A zero economic outlook with no income or
expense keeps balances static, so the overlay is an exact figure rather than a moving target."""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, ExpenseTaxClass, SystemAccountRole
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, LoanParameters, NetWorthCalculation, Subject )
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_D  = Decimal
_US = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_STATIC = EconomicOutlook.constant( EconomicParameters() )   # all rates zero: balances stay put

_YEARLY    = Duration( 1, TimeUnit.YEAR )
_QUARTERLY = Duration( 3, TimeUnit.MONTH )
_MONTHLY   = Duration( 1, TimeUnit.MONTH )

# Static opening position: cash 50k, brokerage 200k (basis 120k -> 80k unrealized gain), pre-tax IRA 300k.
_MEMO = 'Estimated future tax re-estimate'


def _run( *, ordinary_pct = '0', capgains_pct = '0', granularity = _YEARLY, end_year = 2028, loans = None ):
    owner = Subject( 'Owner', date( 1980, 1, 1 ), 'owner' )
    parameters = ForecastParameters(
        start_date       = date( 2026, 1, 1 ),
        end_date         = date( end_year, 12, 31 ),
        filing_status    = FilingStatus.SINGLE,
        statute          = _US,
        subjects         = [ owner ],
        granularity      = granularity,
        economic_outlook = _STATIC,
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '50000' ), _D( '50000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, _D( '200000' ), _D( '120000' ), handle = 'brok' ),
            AssetParameters( 'IRA', AssetClass.PRETAX_RETIREMENT, _D( '300000' ), _D( '0' ),
                             handle = 'ira', owner_handle = 'owner' ) ],
        loans = loans or [],
        net_worth_calculation = NetWorthCalculation(
            ordinary_tax_rate      = Rate.percent( _D( ordinary_pct ) ),
            capital_gains_tax_rate = Rate.percent( _D( capgains_pct ) ) ),
    )
    return Bookkeeper( Forecast( parameters ).run().books )


def _future_tax( reader, through ):
    liability = reader.chart.system_account( SystemAccountRole.ESTIMATED_FUTURE_TAXES )
    return reader.ledger.natural_balance( liability, through = through )


class FutureTaxOverlayTests( unittest.TestCase ):

    # 24% x 300k IRA + 15% x 80k brokerage gain = 72000 + 12000
    _EXPECTED = _D( '84000' )
    _GROSS_NET_WORTH = _D( '550000' )   # 50k + 200k + 300k

    def test_overlay_is_booked_at_t0_and_each_year_end( self ):
        reader = _run( ordinary_pct = '24', capgains_pct = '15' )
        self.assertEqual( _future_tax( reader, date( 2025, 12, 31 ) ), self._EXPECTED )   # t0 (opening date)
        for year in ( 2026, 2027, 2028 ):
            with self.subTest( year = year ):
                self.assertEqual( _future_tax( reader, date( year, 12, 31 ) ), self._EXPECTED )
        reader.assert_balanced()

    def test_net_worth_is_reduced_by_exactly_the_overlay( self ):
        reader = _run( ordinary_pct = '24', capgains_pct = '15' )
        self.assertEqual(
            reader.ledger.net_worth( through = date( 2028, 12, 31 ) ),
            self._GROSS_NET_WORTH - self._EXPECTED )

    def test_assets_are_untouched_by_the_overlay( self ):
        # The overlay is a liability + equity pair; total assets must equal the gross figure, so the
        # overlay changes only the reported net worth, never the asset trajectory the simulation runs on.
        overlaid = _run( ordinary_pct = '24', capgains_pct = '15' )
        plain    = _run()
        for reader in ( overlaid, plain ):
            self.assertEqual(
                reader.ledger.type_total( AccountType.ASSET, through = date( 2028, 12, 31 ) ),
                self._GROSS_NET_WORTH )

    def test_zero_rates_book_no_overlay( self ):
        reader = _run()   # default zero rates
        self.assertEqual( _future_tax( reader, date( 2028, 12, 31 ) ), _D( '0' ) )
        self.assertEqual( reader.ledger.net_worth( through = date( 2028, 12, 31 ) ), self._GROSS_NET_WORTH )
        self.assertFalse(
            any( txn.description == _MEMO for txn in reader.books.transactions ) )

    def test_year_end_overlay_is_invariant_across_granularity( self ):
        year_ends = {
            name: _future_tax(
                _run( ordinary_pct = '24', capgains_pct = '15', granularity = granularity ),
                date( 2028, 12, 31 ) )
            for name, granularity in ( ( 'yearly', _YEARLY ), ( 'quarterly', _QUARTERLY ),
                                       ( 'monthly', _MONTHLY ) ) }
        self.assertEqual( len( set( year_ends.values() ) ), 1, f'overlay differs by granularity: {year_ends}' )

    def test_overlay_flips_a_debt_heavy_household_negative( self ):
        # Gross net worth looks solvent (550k assets - 500k debt = +50k), but the pre-tax IRA cannot be
        # extracted to cover the debt after ordinary tax, so after-overlay net worth is negative. Read at
        # the opening snapshot (loan seeded, not yet serviced) to isolate the extractable-value effect.
        loan = [ LoanParameters(
            'Loan', _D( '500000' ), Rate( _D( '0.05' ) ), Duration( 30, TimeUnit.YEAR ),
            interest_class = ExpenseTaxClass.LIVING ) ]
        opening = date( 2025, 12, 31 )
        plain    = _run( end_year = 2026, loans = loan )
        overlaid = _run( ordinary_pct = '30', capgains_pct = '15', end_year = 2026, loans = loan )
        self.assertGreater( plain.ledger.net_worth( through = opening ), _D( '0' ) )     # +50k, looks solvent
        self.assertLess( overlaid.ledger.net_worth( through = opening ), _D( '0' ) )     # -52k after latent tax


if __name__ == '__main__':
    unittest.main()
