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
    'wage_earner': ( None, _D( '1020650.66552' ), _D( '676672.01319' ) ),
    'retiree': ( 2035, _D( '-3632.32504' ), _D( '190276.19414' ) ),
    'rental_owner': ( None, _D( '1771363.61243' ), _D( '867528.61800' ) ),
    'couple_survivor': ( None, _D( '1552247.85181' ), _D( '235929.08197' ) ),
    'life_events': ( 2044, _D( '-28486.87593' ), _D( '-7386.21271' ) ),
    'gig_worker': ( None, _D( '531683.08757' ), _D( '174423.13303' ) ),
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
