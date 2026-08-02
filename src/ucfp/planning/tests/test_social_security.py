"""Couple-aware Social Security realization (#107): the spousal top-up and its window.

The statutory amounts are tested in `jurisdiction/us/tests/test_social_security.py`; what earns a test
here is the reusable couple-level orchestration -- higher/lower selection, the two-segment
both-collecting window, and the non-earning-spouse (same-date) default -- which the forecast and a later
Social Security timing sweep both depend on. Subjects born Jan 1 so a claiming date is an exact age.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.planning.social_security import (
    GovernmentPensionMember, realized_government_pensions )

_US = GovernmentPension( JurisdictionType.US_FEDERAL )


def _member( handle, birth_year, pia = None, claim_year = None ):
    return GovernmentPensionMember(
        handle, date( birth_year, 1, 1 ),
        None if pia is None else Decimal( pia ),
        None if claim_year is None else date( claim_year, 1, 1 ) )


def _realize( *members ):
    return { r.subject_handle: r for r in realized_government_pensions( list( members ), _US ) }


class RealizationTest( unittest.TestCase ):

    def test_single_member_gets_only_their_own_benefit( self ):
        result = _realize( _member( 'solo', 1960, '2000', 2027 ) )   # PIA 2000, claim at FRA 67
        self.assertEqual( len( result ), 1 )
        self.assertEqual( result[ 'solo' ].amounts.at( date( 2028, 1, 1 ) ).amount, Decimal( '24000' ) )

    def test_couple_lower_earner_steps_up_when_both_are_collecting( self ):
        # lower (PIA 1000) claims at 62 in 2022; higher (PIA 3000) claims at 67 in 2027.
        # own_low at 62 = 1000*0.70*12 = 8400; excess = (1500-1000)*0.65*12 = 3900 once both collect.
        result = _realize(
            _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1000', 2022 ) )
        lower = result[ 'lo' ].amounts
        self.assertEqual( lower.at( date( 2023, 1, 1 ) ).amount, Decimal( '8400' ) )    # own only
        self.assertEqual( lower.at( date( 2028, 1, 1 ) ).amount, Decimal( '12300' ) )   # own + spousal
        self.assertEqual(                                                               # higher: own only
            result[ 'hi' ].amounts.at( date( 2030, 1, 1 ) ).amount, Decimal( '36000' ) )

    def test_lower_earner_claiming_after_the_higher_starts_already_topped_up( self ):
        # higher (PIA 3000) claims at 62 in 2022; lower (PIA 1000) claims at 67 in 2027. Both are
        # already collecting at the lower's start, so one segment carries own + spousal from day one:
        # own_low at FRA 67 = 12000; excess = (1500-1000)*1.0*12 = 6000 -> 18000.
        result = _realize(
            _member( 'hi', 1960, '3000', 2022 ), _member( 'lo', 1960, '1000', 2027 ) )
        lower = result[ 'lo' ].amounts
        self.assertEqual( len( lower.segments ), 1 )
        self.assertEqual( lower.at( date( 2028, 1, 1 ) ).amount, Decimal( '18000' ) )

    def test_entitled_member_without_a_claiming_date_raises( self ):
        with self.assertRaises( ValueError ):
            _realize( _member( 'earner', 1960, '2000' ) )   # PIA entered, no claiming date

    def test_no_top_up_when_own_pia_meets_half_the_higher( self ):
        # own PIA 1600 exceeds half of 3000 (1500): the lower earner keeps a plain own-benefit schedule.
        result = _realize(
            _member( 'hi', 1960, '3000', 2027 ), _member( 'lo', 1960, '1600', 2027 ) )
        self.assertEqual( len( result[ 'lo' ].amounts.segments ), 1 )

    def test_non_earning_spouse_gets_a_pure_spousal_benefit_on_the_earner_date( self ):
        # only the earner (PIA 2400, FRA 67, claims 2027) is filled; the spouse has no entitlement.
        # spouse born 1962 is 65 at the earner's 2027 claim -> 24 months early -> 1200*0.8333*12 = 12000.
        result = _realize(
            _member( 'earner', 1960, '2400', 2027 ), _member( 'spouse', 1962 ) )
        spouse = result[ 'spouse' ]
        self.assertEqual( spouse.start_date, date( 2027, 1, 1 ) )              # the earner's date
        self.assertIsNone( spouse.amounts.at( date( 2026, 1, 1 ) ) )           # nothing before the earner files
        self.assertEqual( spouse.amounts.at( date( 2028, 1, 1 ) ).amount, Decimal( '12000' ) )

    def test_no_entitlements_yields_no_benefit( self ):
        self.assertEqual( _realize( _member( 'a', 1960 ), _member( 'b', 1962 ) ), {} )


if __name__ == '__main__':
    unittest.main()
