"""Couple-aware Social Security benefit on a date (the per-period engine calculation).

Ports the couple-realization cases (spousal top-up, both-collecting timing, non-earning spouse) from the
former `planning.social_security` schedule form to the per-date form the engine now invokes. The statutory
amounts come from `jurisdiction/us`; what earns a test here is the neutral couple orchestration. Subjects
born Jan 1 so a claiming date is an exact age.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.social_security_household import HouseholdMember, household_benefits

_US = GovernmentPension( JurisdictionType.US_FEDERAL )


def _member( handle, birth_year, pia = None, claim_year = None ):
    return HouseholdMember(
        handle, date( birth_year, 1, 1 ),
        None if pia is None else Decimal( pia ),
        None if claim_year is None else date( claim_year, 1, 1 ) )


def _benefits( on_year, *members ):
    return household_benefits( list( members ), _US, date( on_year, 1, 1 ) )


class HouseholdBenefitTest( unittest.TestCase ):

    def test_single_member_own_benefit_starts_at_the_claim( self ):
        solo = _member( 'solo', 1960, '2000', 2027 )                # PIA 2000, FRA 67 -> 24000/yr at 67
        self.assertEqual( _benefits( 2026, solo )[ 'solo' ], Decimal( '0' ) )       # before the claim
        self.assertEqual( _benefits( 2028, solo )[ 'solo' ], Decimal( '24000' ) )

    def test_lower_earner_steps_up_when_both_are_collecting( self ):
        # lower (PIA 1000) claims at 62 in 2022; higher (PIA 3000) claims at 67 in 2027.
        hi, lo = _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1000', 2022 )
        self.assertEqual( _benefits( 2021, hi, lo )[ 'lo' ], Decimal( '0' ) )       # before lo claims
        self.assertEqual( _benefits( 2023, hi, lo )[ 'lo' ], Decimal( '8400' ) )    # own only
        self.assertEqual( _benefits( 2028, hi, lo )[ 'lo' ], Decimal( '12300' ) )   # own + spousal
        self.assertEqual( _benefits( 2030, hi, lo )[ 'hi' ], Decimal( '36000' ) )   # higher: own only

    def test_lower_earner_claiming_after_the_higher_is_topped_up_from_their_claim( self ):
        hi, lo = _member( 'hi', 1960, '3000', 2022 ), _member( 'lo', 1960, '1000', 2027 )
        self.assertEqual( _benefits( 2026, hi, lo )[ 'lo' ], Decimal( '0' ) )       # before lo claims
        self.assertEqual( _benefits( 2028, hi, lo )[ 'lo' ], Decimal( '18000' ) )   # own + spousal at once

    def test_no_top_up_when_own_meets_half_the_higher( self ):
        # own 1600 exceeds half of 3000 (1500): the lower earner keeps their own benefit, no spousal.
        hi, lo = _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1600', 2027 )
        self.assertEqual( _benefits( 2028, hi, lo )[ 'lo' ], Decimal( '19200' ) )   # 1600 * 12, own only

    def test_non_earning_spouse_gets_a_pure_spousal_from_the_earner_date( self ):
        earner, spouse = _member( 'earner', 1960, '2400', 2027 ), _member( 'spouse', 1962 )
        self.assertEqual( _benefits( 2026, earner, spouse )[ 'spouse' ], Decimal( '0' ) )   # not filed yet
        self.assertEqual( _benefits( 2028, earner, spouse )[ 'spouse' ], Decimal( '12000' ) )

    def test_entitled_member_without_a_claiming_date_raises( self ):
        with self.assertRaises( ValueError ):
            _benefits( 2028, _member( 'earner', 1960, '2000' ) )

    def test_no_entitlements_yields_no_benefit( self ):
        self.assertEqual( _benefits( 2028, _member( 'a', 1960 ), _member( 'b', 1962 ) ), {} )


if __name__ == '__main__':
    unittest.main()
