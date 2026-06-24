"""Tests for the Social Security claiming-age benefit adjustment (US SSA schedule)."""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.tax.us.social_security import full_retirement_age_months, realized_annual_benefit


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
    published whole-percent factors."""

    _PIA = Decimal( '1000' )

    def _annual_at( self, birth_year, claiming_age ):
        return realized_annual_benefit( self._PIA, date( birth_year, 1, 1 ), claiming_age )

    def test_full_retirement_age_pays_pia( self ):
        self.assertEqual( self._annual_at( 1960, 67 ), Decimal( '12000' ) )

    def test_earliest_claim_at_62_is_70_percent_for_fra_67( self ):
        # 60 months early = 36*(5/9%) + 24*(5/12%) = 20% + 10% = 30% reduction -> 70%.
        self.assertEqual( self._annual_at( 1960, 62 ), Decimal( '8400' ) )

    def test_delayed_to_70_is_124_percent_for_fra_67( self ):
        # 36 months late * (2/3%) = 24% credit -> 124%.
        self.assertEqual( self._annual_at( 1960, 70 ), Decimal( '14880' ) )

    def test_fra_66_claim_at_62_is_75_percent( self ):
        # 48 months early = 36*(5/9%) + 12*(5/12%) = 20% + 5% = 25% reduction -> 75%.
        self.assertEqual( self._annual_at( 1950, 62 ), Decimal( '9000' ) )

    def test_fra_66_delayed_to_70_is_132_percent( self ):
        # 48 months late * (2/3%) = 32% credit -> 132%.
        self.assertEqual( self._annual_at( 1950, 70 ), Decimal( '15840' ) )
