"""Release-gate characterization smoke: each feature-spanning granularity profile's full multi-year run
pins its terminal net worth, depletion year, and total lifetime tax, and its books balance. A change
here is a material shift in composed forecast behaviour -- regenerate the golden values only when the
change is intended.

Tagged 'e2e' so it runs in the release gate (`make test-e2e` / `make check-release`), not the default
dev gate. Unlike the granularity suite (which asserts cross-granularity *invariance*), this pins
*magnitudes*, catching a systematic bug that is granularity-consistent."""
import unittest
from decimal import Decimal

from django.test import tag

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.tests.granularity_harness import outcome, total_lifetime_tax
from ucfp.forecast.tests.granularity_profiles import PROFILES, full_tier

_D = Decimal

# ( depletion_year, terminal_net_worth, total_lifetime_tax ) per profile at the full tier (real
# economics + the profile's complete cash policy), January start. Regenerate deliberately when an engine
# or 2026-parameter change is intended -- a diff here means composed behaviour moved.
_GOLDEN = {
    'wage_earner': ( None, _D( '1039554.99206' ), _D( '678947.61731' ) ),
    'retiree': ( 2036, _D( '-100132.82616' ), _D( '195456.71743' ) ),
    'rental_owner': ( None, _D( '1784286.53649' ), _D( '872566.42882' ) ),
    'couple_survivor': ( None, _D( '1556994.53039' ), _D( '236576.67540' ) ),
    'life_events': ( 2044, _D( '-29182.71688' ), _D( '-7426.08413' ) ),
    'gig_worker': ( None, _D( '546146.80897' ), _D( '174425.71870' ) ),
}


@tag( 'e2e' )
class ForecastGoldenTrajectoryTests( unittest.TestCase ):

    def test_the_golden_set_covers_every_profile( self ):
        # A new granularity profile must gain a golden entry (else it silently escapes the gate).
        self.assertEqual( set( _GOLDEN ), set( PROFILES ) )

    def test_every_profile_matches_its_golden_outcome_and_balances( self ):
        for name, build in PROFILES.items():
            with self.subTest( profile = name ):
                params = full_tier( build() )
                result = Forecast( params ).run()
                Bookkeeper( result.books ).assert_balanced()   # double-entry conservation holds
                run_outcome = outcome( result, params )
                total_tax   = total_lifetime_tax( result, params )
                depletion, terminal, tax = _GOLDEN[ name ]
                self.assertEqual( run_outcome.depletion_year, depletion )
                self.assertEqual( run_outcome.terminal_net_worth, terminal )
                self.assertEqual( total_tax, tax )


if __name__ == '__main__':
    unittest.main()
