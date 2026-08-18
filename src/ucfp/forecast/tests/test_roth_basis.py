"""Roth basis tracking (issue #185).

Phase 2a: a Roth now carries a real basis -- its opening balance is 100% basis -- rather than seeding
at zero basis like a pre-tax account. Behavior is unchanged this phase: a Roth withdrawal is still
fully tax-free (later phases tax the earnings above basis when withdrawn before 59.5). These tests pin
that the basis is seeded and that withdrawals stay tax-free.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, ScheduledRealization, Subject )
from ucfp.forecast.tests.tax_helpers import total_income_tax
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )   # age 51 in 2026


def _parameters( *, events = (), outlook = None ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
            # Opening 100k, all basis (cost_basis = opening) -- accepted now that Roth is not zero-basis.
            AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                             handle = 'roth', owner_handle = 'subject-a' ) ],
        events        = list( events ),
        economic_outlook = outlook if outlook is not None else EconomicOutlook(),
    )


class RothBasisSeedingTests( unittest.TestCase ):
    """A Roth seeds its opening balance as basis (cost), not as unrealized gain."""

    def test_roth_accepts_a_nonzero_basis_and_seeds_cost_at_opening( self ):
        # Before phase 2a a Roth with cost_basis != 0 was rejected by the zero-basis rule; now its
        # opening balance is basis, so the holding seeds cost = opening and valuation = 0.
        reader  = Bookkeeper( Forecast( _parameters() ).run().books )
        roth    = reader.chart.account( 'roth' )
        through = date( 2026, 12, 31 )
        self.assertEqual( reader.ledger.natural_balance( roth, through = through ), Decimal( '100000' ) )
        self.assertEqual( reader.ledger.market_value( roth, through = through ), Decimal( '100000' ) )


class RothWithdrawalStaysTaxFreeTests( unittest.TestCase ):
    """With basis now tracked, a Roth withdrawal remains fully tax-free this phase -- even when the
    holding has grown, so its earnings (the taxable slice in later phases) are still free today."""

    _GROWTH = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '0.10' ) ) ) )

    def test_roth_withdrawal_is_tax_free_even_with_earnings( self ):
        reader = Bookkeeper( Forecast( _parameters(
            outlook = self._GROWTH,
            events  = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', Decimal( '40000' ) ) ] ) ).run().books )
        self.assertEqual( total_income_tax( reader ), Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
