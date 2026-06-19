"""Tests for scheduled money-movement events resolved by the Forecast.

Covers the resolution of a `ScheduledEvent` (which names holdings) into the period-layer
`PeriodEvent` (which holds accounts), and the destination semantics of the one realization
mechanism: a transfer (no tax), a sale to the cash hub, and a conversion whose proceeds
land in another holding. A separate case exercises the depreciating-asset path -- a sale
that realizes a (tax-free) loss -- which previously had no realized-gain account at all.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    ScheduledRealization,
    ScheduledTransfer,
    Subject,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus


def _holding( reader, name ):
    return next( account for account in reader.chart.holdings() if account.name == name )


class EventResolutionTests( unittest.TestCase ):

    def test_events_move_value_and_preserve_net_worth( self ):
        # A half-year horizon (no Dec-31 close, so no tax settles) isolates the events'
        # net-worth-neutral mechanics: a transfer, a sale to cash, and a conversion to Roth.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 6, 30 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ) ),
                AssetParameters( 'CD', AssetClass.CDS, Decimal( '0' ) ),
                AssetParameters( 'Stocks', AssetClass.STOCKS, Decimal( '50000' ) ),
                AssetParameters( 'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '40000' ) ),
                AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '0' ) ),
            ],
            events        = [
                ScheduledTransfer( date( 2026, 3, 1 ), 'Cash', 'CD', Decimal( '20000' ) ),
                ScheduledRealization( date( 2026, 3, 1 ), 'Stocks', Decimal( '50000' ) ),
                ScheduledRealization( date( 2026, 3, 1 ), 'IRA', Decimal( '40000' ), 'Roth' ),
            ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        through = date( 2026, 6, 30 )
        # opening net worth is preserved: no growth, no tax, and every event is neutral
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '190000' ) )
        # cash: 100k less the 20k transfer plus the 50k stock proceeds
        self.assertEqual( ledger.market_value( _holding( reader, 'Cash' ), through = through ),
                          Decimal( '130000' ) )
        self.assertEqual( ledger.market_value( _holding( reader, 'CD' ), through = through ),
                          Decimal( '20000' ) )
        self.assertEqual( ledger.market_value( _holding( reader, 'Stocks' ), through = through ),
                          Decimal( '0' ) )
        # the conversion empties the IRA into the Roth holding
        self.assertEqual( ledger.market_value( _holding( reader, 'IRA' ), through = through ),
                          Decimal( '0' ) )
        self.assertEqual( ledger.market_value( _holding( reader, 'Roth' ), through = through ),
                          Decimal( '40000' ) )

    def test_pretax_withdrawal_recognizes_the_whole_amount_as_ordinary( self ):
        # zero-basis seeding: a pre-tax account opens with no cost basis, so a withdrawal is
        # wholly ordinary income (not just appreciation). With no growth, the entire 40k --
        # not zero -- lands in the Ordinary revenue account.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 6, 30 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ) ),
                AssetParameters( 'IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '40000' ) ),
            ],
            events        = [ ScheduledRealization( date( 2026, 3, 1 ), 'IRA', Decimal( '40000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        through = date( 2026, 6, 30 )
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY )
        self.assertEqual( ledger.natural_balance( ordinary ), Decimal( '40000' ) )
        # the withdrawal lands in cash; recognizing it is net-worth-neutral (no tax this half-year)
        self.assertEqual( ledger.market_value( _holding( reader, 'Cash' ), through = through ),
                          Decimal( '40000' ) )
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '40000' ) )

    def test_selling_a_depreciated_asset_realizes_a_tax_free_loss( self ):
        # A depreciating asset has no taxable realized gain; selling it must still resolve
        # (the loss routes to the tax-free class) rather than fail for want of a gain account.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ) ),
                AssetParameters( 'Car', AssetClass.DEPRECIATING, Decimal( '30000' ) ),
            ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( depreciation_rate = Rate( Decimal( '0.20' ) ) ) ),
            events        = [ ScheduledRealization( date( 2026, 7, 1 ), 'Car', Decimal( '30000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        through = date( 2026, 12, 31 )
        # the car depreciated 20% (30k -> 24k) before the sale; selling caps at that value
        self.assertEqual( ledger.market_value( _holding( reader, 'Car' ), through = through ),
                          Decimal( '0' ) )
        self.assertEqual( ledger.market_value( _holding( reader, 'Cash' ), through = through ),
                          Decimal( '24000' ) )
        # the 6k decline is the only net-worth change; the realized loss is excluded from tax
        self.assertEqual( ledger.net_worth( through = through ), Decimal( '24000' ) )


if __name__ == '__main__':
    unittest.main()
