"""Tests for real-estate sales and their tax wiring.

A primary-residence sale realizes into its own `RESIDENCE_SECTION_121_GAIN` account; the
engine excludes up to the filing-status cap and taxes only the remainder as a long-term
gain. (Rental §1250 recapture is wired through `TaxContext.properties`, but its end-to-end
assertion is deferred along with the t0-basis/accumulated-depreciation modeling question.)
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
    Subject,
)
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection


class Section121Tests( unittest.TestCase ):

    def test_residence_gain_under_cap_is_excluded( self ):
        # The home appreciates 25% (800k -> 1,000k) and is sold; the 200k gain is well under
        # the $500k MFJ §121 cap, so it is wholly excluded and no tax is taken.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ), Subject( 'B', date( 1959, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'Home', AssetClass.REAL_ESTATE_RESIDENCE, Decimal( '800000' ), Decimal( '800000' ),
                    handle = 'Home' ),
            ],
            economic_outlook = EconomicOutlook.constant(
                EconomicParameters( real_estate_appreciation = Rate( Decimal( '0.25' ) ) ) ),
            events        = [ ScheduledRealization( date( 2026, 7, 1 ), 'Home', Decimal( '1000000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        residence_gain = reader.chart.income_account( IncomeTaxClass.RESIDENCE_SECTION_121_GAIN )
        # the gain realizes into its own §121 account, distinct from long-term gains
        self.assertEqual( ledger.natural_balance( residence_gain ), Decimal( '200000' ) )
        # under the cap it is fully excluded: no tax taken, so the appreciated value is intact
        self.assertEqual( ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '1000000' ) )

    def test_residence_gain_is_measured_from_purchase_basis( self ):
        # The home was bought for 200k and is worth 600k at t0 (a 400k embedded gain). With no
        # further appreciation it sells for 600k; the gain is measured from the 200k basis, not
        # the t0 value (which would give 0) -- proving the basis/market split feeds §121.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ Subject( 'A', date( 1958, 1, 1 ) ), Subject( 'B', date( 1959, 1, 1 ) ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'Home', AssetClass.REAL_ESTATE_RESIDENCE, Decimal( '600000' ), Decimal( '200000' ),
                    handle = 'Home' ),
            ],
            events        = [ ScheduledRealization( date( 2026, 7, 1 ), 'Home', Decimal( '600000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        residence_gain = reader.chart.income_account( IncomeTaxClass.RESIDENCE_SECTION_121_GAIN )
        # gain = 600k proceeds - 200k basis = 400k (not 0, as it would be from the t0 value)
        self.assertEqual( ledger.natural_balance( residence_gain ), Decimal( '400000' ) )
        # under the $500k MFJ cap -> fully excluded -> no tax, value intact
        self.assertEqual( ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '600000' ) )


class SecondHomeSaleTests( unittest.TestCase ):
    """A second (vacation) home is personal-use like the residence -- its gain floors at zero (loss
    non-deductible) -- but gets no §121 exclusion, so the whole gain is taxed as long-term."""

    _STATUTE = StatuteProfile(
        JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
    _SUBJECTS = [ Subject( 'A', date( 1958, 1, 1 ) ), Subject( 'B', date( 1959, 1, 1 ) ) ]

    def test_second_home_gain_is_taxed_with_no_exclusion( self ):
        # Bought for 200k, worth 600k at t0 (a 400k embedded gain), sold for 600k with no further
        # appreciation. The 400k realizes into its own account and -- unlike a residence under the
        # §121 cap -- is taxed, so net worth ends below the 600k proceeds.
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute       = self._STATUTE,
            subjects      = self._SUBJECTS,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'Cabin', AssetClass.REAL_ESTATE_SECOND_HOME,
                    Decimal( '600000' ), Decimal( '200000' ), handle = 'Cabin' ),
            ],
            events        = [ ScheduledRealization( date( 2026, 7, 1 ), 'Cabin', Decimal( '600000' ) ) ],
        )
        reader = Bookkeeper( Forecast( parameters ).run().books )
        ledger = reader.ledger
        second_home_gain = reader.chart.income_account( IncomeTaxClass.SECOND_HOME_GAIN )
        # the gain realizes into its own account, distinct from long-term gains
        self.assertEqual( ledger.natural_balance( second_home_gain ), Decimal( '400000' ) )
        # No exclusion: the whole 400k is a long-term gain and is taxed. The exact ending net worth
        # pins that -- a §121-style exclusion would leave materially more, so this discriminates the
        # no-exclusion rule rather than merely asserting "some tax was taken".
        self.assertEqual( ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '554460.00000' ) )

    def test_second_home_loss_does_not_offset_other_gains( self ):
        # A stock realizes a 200k long-term gain; a second home bought for 200k but worth only 100k
        # is sold at a 100k loss. The personal-use loss is non-deductible (floored), so it must not
        # net against the stock gain -- the ending net worth is identical whether or not the
        # loss-making cabin is sold (were the loss deductible, selling it would cut the tax). The
        # stock gain is 200k (not 100k) deliberately: it clears the MFJ 0% long-term-gains bracket
        # into a taxpaying regime, so a wrongly-deducted loss would actually move the tax -- at a
        # smaller gain both branches sit at 0% and the test would pass vacuously.
        def net_worth( sell_cabin : bool ) -> Decimal:
            events = [ ScheduledRealization( date( 2026, 7, 1 ), 'Stock', Decimal( '200000' ) ) ]
            if sell_cabin:
                events.append( ScheduledRealization( date( 2026, 7, 1 ), 'Cabin', Decimal( '100000' ) ) )
            parameters = ForecastParameters(
                start_date    = date( 2026, 1, 1 ),
                end_date      = date( 2026, 12, 31 ),
                filing_status = FilingStatus.MARRIED_JOINT,
                statute       = self._STATUTE,
                subjects      = self._SUBJECTS,
                assets        = [
                    AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                    AssetParameters(
                        'Stock', AssetClass.STOCKS, Decimal( '200000' ), Decimal( '0' ), handle = 'Stock' ),
                    AssetParameters(
                        'Cabin', AssetClass.REAL_ESTATE_SECOND_HOME,
                        Decimal( '100000' ), Decimal( '200000' ), handle = 'Cabin' ),
                ],
                events        = events,
            )
            reader = Bookkeeper( Forecast( parameters ).run().books )
            return reader.ledger.net_worth( through = date( 2026, 12, 31 ) )

        self.assertEqual( net_worth( sell_cabin = True ), net_worth( sell_cabin = False ) )


if __name__ == '__main__':
    unittest.main()
