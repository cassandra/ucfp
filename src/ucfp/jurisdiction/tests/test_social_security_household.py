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
from ucfp.jurisdiction.social_security_household import (
    HouseholdMember, household_benefit_breakdown, household_benefits )

_US = GovernmentPension( JurisdictionType.US_FEDERAL )


def _member( handle, birth_year, pia = None, claim_year = None, death_year = None ):
    return HouseholdMember(
        handle, date( birth_year, 1, 1 ),
        None if pia is None else Decimal( pia ),
        None if claim_year is None else date( claim_year, 1, 1 ),
        None if death_year is None else date( death_year, 1, 1 ) )


def _benefits( on_year, *members ):
    return household_benefits( list( members ), _US, date( on_year, 1, 1 ) )


def _breakdown( on_year, *members ):
    return household_benefit_breakdown( list( members ), _US, date( on_year, 1, 1 ) )


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

    def test_a_non_earning_spouse_spousal_waits_for_age_62_when_the_earner_files_earlier( self ):
        # A spousal benefit is not payable before age 62. The earner (born 1958) files at 62 in 2020, but the
        # spouse (born 1968) does not reach 62 until 2030 -- so their spousal begins in 2030, not at the
        # earner's earlier filing. (Regression: the spouse was previously paid from the earner's date.)
        earner, spouse = _member( 'earner', 1958, '2400', 2020 ), _member( 'spouse', 1968 )
        self.assertEqual( _benefits( 2029, earner, spouse )[ 'spouse' ], Decimal( '0' ) )   # spouse is 61
        self.assertGreater( _benefits( 2030, earner, spouse )[ 'spouse' ], Decimal( '0' ) )  # spouse turns 62
        # Once payable it is the age-62 reduced spousal (claimed at the earliest, not the earner's date).
        spouse_at_62 = _member( 'spouse', 1968, '0', 2030 )
        self.assertEqual( _benefits( 2031, earner, spouse )[ 'spouse' ],
                          _breakdown( 2031, earner, spouse_at_62 )[ 'spouse' ].spousal )

    def test_entitled_member_without_a_claiming_date_raises( self ):
        with self.assertRaises( ValueError ):
            _benefits( 2028, _member( 'earner', 1960, '2000' ) )

    def test_no_entitlements_yields_no_benefit( self ):
        self.assertEqual( _benefits( 2028, _member( 'a', 1960 ), _member( 'b', 1962 ) ), {} )


class HouseholdSurvivorTest( unittest.TestCase ):
    """After the first death the survivor takes the larger of the two own benefits (spousal ends); the
    decedent is gone the year after their death."""

    def test_survivor_takes_the_larger_benefit_after_the_higher_earner_dies( self ):
        hi = _member( 'hi', 1960, '3000', 2027, death_year = 2030 )
        lo = _member( 'lo', 1960, '1000', 2027 )
        self.assertEqual( _benefits( 2030, hi, lo )[ 'lo' ], Decimal( '18000' ) )   # both alive through 2030
        self.assertEqual( _benefits( 2031, hi, lo )[ 'lo' ], Decimal( '36000' ) )   # survivor -> higher
        self.assertEqual( _benefits( 2031, hi, lo )[ 'hi' ], Decimal( '0' ) )       # decedent stops

    def test_higher_earner_unaffected_when_the_lower_earner_dies( self ):
        hi = _member( 'hi', 1960, '3000', 2027 )
        lo = _member( 'lo', 1960, '1000', 2027, death_year = 2030 )
        self.assertEqual( _benefits( 2031, hi, lo )[ 'hi' ], Decimal( '36000' ) )   # keeps own
        self.assertEqual( _benefits( 2031, hi, lo )[ 'lo' ], Decimal( '0' ) )

    def test_non_earning_spouse_becomes_a_survivor_on_the_earner_death( self ):
        earner = _member( 'earner', 1960, '2400', 2027, death_year = 2030 )
        spouse = _member( 'spouse', 1962 )
        self.assertEqual( _benefits( 2028, earner, spouse )[ 'spouse' ], Decimal( '12000' ) )   # spousal
        self.assertEqual( _benefits( 2031, earner, spouse )[ 'spouse' ], Decimal( '28800' ) )   # survivor

    def test_inherited_benefit_waits_for_the_decedent_claim_when_death_precedes_it( self ):
        # Regression: the decedent's side of the survivor benefit was ungated, so when death fell before the
        # decedent's own claim date the survivor was paid the (larger) inherited benefit years early -- which
        # inflated the SS-timing calculator's actuarial expected values in pre-claim years. The survivor
        # should get only their own benefit until the decedent's claim date, then the inherited one.
        hi        = _member( 'hi', 1960, '3000', 2030, death_year = 2025 )   # claims at 70; dies before it
        lo        = _member( 'lo', 1960, '1000', 2027 )                      # survivor; own from 2027
        inherited = _US.realized_annual_benefit( Decimal( '3000' ), date( 1960, 1, 1 ), date( 2030, 1, 1 ) )
        self.assertEqual( _benefits( 2027, hi, lo )[ 'lo' ], Decimal( '12000' ) )   # own only, pre-claim
        self.assertEqual( _benefits( 2029, hi, lo )[ 'lo' ], Decimal( '12000' ) )   # right up to the claim
        self.assertEqual( _benefits( 2030, hi, lo )[ 'lo' ], inherited )            # inherited benefit begins
        self.assertGreater( inherited, Decimal( '12000' ) )                         # and it is the larger


class BenefitBreakdownTest( unittest.TestCase ):
    """The own / spousal / survivor split (`household_benefit_breakdown`); its per-member totals are what
    `household_benefits` returns."""

    def test_a_couple_splits_into_own_and_the_lower_spousal( self ):
        hi, lo = _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1000', 2027 )
        parts = _breakdown( 2028, hi, lo )
        self.assertEqual( parts[ 'hi' ].own, Decimal( '36000' ) )       # higher: own only
        self.assertEqual( parts[ 'hi' ].spousal, Decimal( '0' ) )
        self.assertEqual( parts[ 'lo' ].own, Decimal( '12000' ) )       # lower: own 1000*12
        self.assertEqual( parts[ 'lo' ].spousal, Decimal( '6000' ) )    # + spousal excess (half 3000 - 1000)
        self.assertEqual( parts[ 'lo' ].total, Decimal( '18000' ) )

    def test_the_survivor_part_replaces_own_and_spousal_after_a_death( self ):
        hi = _member( 'hi', 1960, '3000', 2027, death_year = 2030 )
        lo = _member( 'lo', 1960, '1000', 2027 )
        parts = _breakdown( 2031, hi, lo )
        self.assertEqual( parts[ 'lo' ].own, Decimal( '0' ) )
        self.assertEqual( parts[ 'lo' ].spousal, Decimal( '0' ) )
        self.assertEqual( parts[ 'lo' ].survivor, Decimal( '36000' ) )  # steps up to the higher benefit

    def test_a_non_earning_spouse_is_pure_spousal( self ):
        earner, spouse = _member( 'earner', 1960, '2400', 2027 ), _member( 'spouse', 1962 )
        parts = _breakdown( 2028, earner, spouse )
        self.assertEqual( parts[ 'spouse' ].own, Decimal( '0' ) )
        self.assertEqual( parts[ 'spouse' ].spousal, Decimal( '12000' ) )

    def test_totals_match_household_benefits( self ):
        hi, lo = _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1000', 2022 )
        parts   = _breakdown( 2028, hi, lo )
        totals  = _benefits( 2028, hi, lo )
        self.assertEqual( { h: p.total for h, p in parts.items() }, totals )


if __name__ == '__main__':
    unittest.main()
