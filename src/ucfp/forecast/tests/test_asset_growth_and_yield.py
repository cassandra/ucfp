"""Exact posting of asset growth and yield -- the forecast-level gap the rate-*mapping* unit tests in
test_economic_outlook.py leave open. Appreciation grows a holding's market value by its class rate;
a distribution posts its class yield to the owning revenue account. One holding, one rate, one year,
so the expected amount is closed-form."""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import AssetParameters, ForecastParameters, Subject
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_D       = Decimal
_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
_THROUGH = date( 2026, 12, 31 )


def _run( holding, economics ):
    return Bookkeeper( Forecast( ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, _D( '0' ), _D( '0' ) ),
            holding ],
        economic_outlook = EconomicOutlook.constant( economics ),
    ) ).run().books )


def _run_single( holding, economics ):
    """Run a forecast whose only asset is `holding` -- so a distributing cash hub can be seeded
    with a chosen (here negative) opening balance without a second cash account confusing the
    hub lookup."""
    return Bookkeeper( Forecast( ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = [ holding ],
        economic_outlook = EconomicOutlook.constant( economics ),
    ) ).run().books )


class AssetGrowthAndYieldTests( unittest.TestCase ):

    def test_appreciation_grows_market_value_by_the_class_rate( self ):
        holding = AssetParameters( 'Brokerage', AssetClass.STOCKS, _D( '100000' ), _D( '100000' ),
                                   handle = 'brokerage' )
        reader  = _run( holding, EconomicParameters( stock_appreciation = Rate( _D( '0.10' ) ) ) )
        market = reader.ledger.market_value( reader.chart.account( 'brokerage' ), through = _THROUGH )
        self.assertEqual( market, _D( '110000' ) )   # 100,000 + 10% appreciation, held unrealized

    def test_dividend_yield_posts_to_the_qualified_dividends_account( self ):
        holding = AssetParameters(
            'Dividend Fund', AssetClass.DIVIDEND_STOCKS, _D( '100000' ), _D( '100000' ),
            handle = 'dividends' )
        reader  = _run( holding, EconomicParameters( stock_dividend = Rate( _D( '0.03' ) ) ) )
        dividends = reader.chart.income_account( IncomeTaxClass.QUALIFIED_DIVIDENDS )
        self.assertEqual( reader.ledger.natural_balance( dividends ), _D( '3000' ) )   # 3% of 100,000

    def test_bond_interest_posts_to_the_taxable_interest_account( self ):
        holding = AssetParameters(
            'Bonds', AssetClass.BONDS, _D( '100000' ), _D( '100000' ), handle = 'bonds' )
        reader  = _run( holding, EconomicParameters( bond_interest = Rate( _D( '0.04' ) ) ) )
        interest = reader.chart.income_account( IncomeTaxClass.TAXABLE_INTEREST )
        self.assertEqual( reader.ledger.natural_balance( interest ), _D( '4000' ) )   # 4% of 100,000

    def test_no_distribution_is_recognized_on_a_non_positive_balance( self ):
        # A depleted forecast can carry the cash hub negative (tax settles after the single funding
        # pass), and that negative balance opens the next period. Yield must not be posted on it:
        # the distribution rate on a negative principal would book negative "interest income" and
        # deepen the shortfall. Seeding cash negative stands in for that mid-forecast state.
        holding  = AssetParameters( 'Cash', AssetClass.CASH, _D( '-1000' ), _D( '-1000' ), handle = 'cash' )
        reader   = _run_single( holding, EconomicParameters( savings_interest = Rate( _D( '0.02' ) ) ) )
        interest = reader.chart.income_account( IncomeTaxClass.TAXABLE_INTEREST )
        self.assertEqual( reader.ledger.natural_balance( interest ), _D( '0' ) )   # no yield on an overdraft


if __name__ == '__main__':
    unittest.main()
