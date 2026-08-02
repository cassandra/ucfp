"""Tests for the Social Security claiming-date benefit adjustment (US SSA schedule)."""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.jurisdiction.us.social_security import (
    full_retirement_age_months, realized_annual_benefit, spousal_excess_annual_benefit )


class FullRetirementAgeTest( unittest.TestCase ):

    def test_birth_year_schedule( self ):
        self.assertEqual( full_retirement_age_months( 1930 ), 65 * 12 )
        self.assertEqual( full_retirement_age_months( 1938 ), 65 * 12 + 2 )
        self.assertEqual( full_retirement_age_months( 1943 ), 66 * 12 )
        self.assertEqual( full_retirement_age_months( 1955 ), 66 * 12 + 2 )
        self.assertEqual( full_retirement_age_months( 1960 ), 67 * 12 )
        self.assertEqual( full_retirement_age_months( 1990 ), 67 * 12 )


class RealizedBenefitTest( unittest.TestCase ):
    """A PIA of $1,000/month is $12,000/yr at full retirement age; the anchors are the SSA's
    published whole-percent factors. Subjects are born Jan 1 so a claiming date is an exact age."""

    _PIA = Decimal( '1000' )

    def _annual_at( self, birth_year, claiming_date ):
        return realized_annual_benefit( self._PIA, date( birth_year, 1, 1 ), claiming_date )

    def _claim_on_birthday( self, birth_year, claiming_age ):
        """Claim on the birthday at `claiming_age` (subject born Jan 1) -- a whole-year anchor."""
        return self._annual_at( birth_year, date( birth_year + claiming_age, 1, 1 ) )

    def test_full_retirement_age_pays_pia( self ):
        self.assertEqual( self._claim_on_birthday( 1960, 67 ), Decimal( '12000' ) )

    def test_earliest_claim_at_62_is_70_percent_for_fra_67( self ):
        # 60 months early = 36*(5/9%) + 24*(5/12%) = 20% + 10% = 30% reduction -> 70%.
        self.assertEqual( self._claim_on_birthday( 1960, 62 ), Decimal( '8400' ) )

    def test_delayed_to_70_is_124_percent_for_fra_67( self ):
        # 36 months late * (2/3%) = 24% credit -> 124%.
        self.assertEqual( self._claim_on_birthday( 1960, 70 ), Decimal( '14880' ) )

    def test_fra_66_claim_at_62_is_75_percent( self ):
        # 48 months early = 36*(5/9%) + 12*(5/12%) = 20% + 5% = 25% reduction -> 75%.
        self.assertEqual( self._claim_on_birthday( 1950, 62 ), Decimal( '9000' ) )

    def test_fra_66_delayed_to_70_is_132_percent( self ):
        # 48 months late * (2/3%) = 32% credit -> 132%.
        self.assertEqual( self._claim_on_birthday( 1950, 70 ), Decimal( '15840' ) )

    def test_six_months_early_reduces_by_the_month( self ):
        # FRA 67 (2027-01-01); 6 months early = 6*(5/9%) = 1/30 reduction -> 29/30 * 12000.
        self.assertEqual( self._annual_at( 1960, date( 2026, 7, 1 ) ), Decimal( '11600' ) )

    def test_six_months_late_credits_by_the_month( self ):
        # FRA 67 (2027-01-01); 6 months late = 6*(2/3%) = 1/25 credit -> 26/25 * 12000.
        self.assertEqual( self._annual_at( 1960, date( 2027, 7, 1 ) ), Decimal( '12480' ) )

    def test_claiming_day_of_month_is_ignored( self ):
        # The adjustment is per claiming month, so any day in July 2026 pays the same.
        self.assertEqual(
            self._annual_at( 1960, date( 2026, 7, 31 ) ),
            self._annual_at( 1960, date( 2026, 7, 1 ) ) )

    def test_mid_year_claim_lands_between_whole_year_anchors( self ):
        # The regression: a month between two birthdays pays strictly between their whole-year
        # benefits, which the old year-granular API could not express.
        at_66      = self._claim_on_birthday( 1960, 66 )
        at_67      = self._claim_on_birthday( 1960, 67 )
        mid_year   = self._annual_at( 1960, date( 2026, 7, 1 ) )
        self.assertLess( at_66, mid_year )
        self.assertLess( mid_year, at_67 )


class SpousalExcessTest( unittest.TestCase ):
    """The spousal top-up = the excess of half the higher earner's PIA over the lower earner's own
    PIA, reduced for early claiming by the lower earner's own FRA schedule. Subjects born Jan 1 so a
    claiming date is an exact age; the anchors are the SSA whole-percent spousal factors."""

    def _spousal( self, pia_high, pia_low, birth_year, claiming_age ):
        return spousal_excess_annual_benefit(
            Decimal( pia_high ), Decimal( pia_low ),
            date( birth_year, 1, 1 ), date( birth_year + claiming_age, 1, 1 ) )

    def test_at_fra_pays_the_full_half_pia_excess( self ):
        # half of 2000 = 1000, less own 500 = 500/mo excess -> 6000/yr, no reduction at FRA 67.
        self.assertEqual( self._spousal( '2000', '500', 1960, 67 ), Decimal( '6000' ) )

    def test_no_delayed_credits_past_fra( self ):
        # the spousal benefit caps at 50% of PIA -- claiming at 70 pays the same as at FRA.
        self.assertEqual( self._spousal( '2000', '500', 1960, 70 ),
                          self._spousal( '2000', '500', 1960, 67 ) )

    def test_early_claim_at_62_reduces_by_35_percent_for_fra_67( self ):
        # 60 months early = 36*(25/36%) + 24*(5/12%) = 25% + 10% = 35% reduction -> 65% of 6000.
        self.assertEqual( self._spousal( '2000', '500', 1960, 62 ), Decimal( '3900' ) )

    def test_early_claim_at_62_reduces_by_30_percent_for_fra_66( self ):
        # 48 months early = 36*(25/36%) + 12*(5/12%) = 25% + 5% = 30% reduction -> 70% of 6000.
        self.assertEqual( self._spousal( '2000', '500', 1950, 62 ), Decimal( '4200' ) )

    def test_floors_at_zero_when_own_pia_meets_half_the_higher( self ):
        # own 1200 already exceeds half of 2000 (1000): no top-up.
        self.assertEqual( self._spousal( '2000', '1200', 1960, 67 ), Decimal( '0' ) )

    def test_zero_own_pia_is_a_pure_spousal_benefit( self ):
        # a non-earning spouse: half of 2000 = 1000/mo -> 12000/yr at FRA.
        self.assertEqual( self._spousal( '2000', '0', 1960, 67 ), Decimal( '12000' ) )

    def test_reduction_is_capped_at_the_age_62_maximum( self ):
        # claiming below 62 is not allowed, so a much-younger spouse floors at the 62 reduction.
        self.assertEqual( self._spousal( '2000', '0', 1960, 59 ),
                          self._spousal( '2000', '0', 1960, 62 ) )
