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
    'wage_earner': ( None, _D( '982944.30258' ), _D( '681208.24153' ) ),
    'retiree': ( 2035, _D( '-5508.76211' ), _D( '191464.82502' ) ),
    'rental_owner': ( None, _D( '1773406.70794' ), _D( '868324.92931' ) ),
    'couple_survivor': ( None, _D( '1539365.69213' ), _D( '239242.28298' ) ),
    'life_events': ( 2044, _D( '-29478.71013' ), _D( '-7369.68025' ) ),
    'gig_worker': ( None, _D( '536939.65647' ), _D( '174158.71051' ) ),
    'lumpy_income': ( None, _D( '1823281.61222' ), _D( '774392.88926' ) ),
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
