"""Tests for the `GovernmentPension` facade's benefit estimator -- the jurisdiction-neutral entry point
callers use to seed an FRA-benefit fact from covered wages without testing the jurisdiction themselves."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.us.social_security import estimated_pia_monthly_current


class BenefitEstimatorTest( unittest.TestCase ):

    def setUp( self ):
        self._pension = GovernmentPension( JurisdictionType.US_FEDERAL )

    def test_us_advertises_a_benefit_estimator( self ):
        self.assertTrue( self._pension.has_benefit_estimator() )

    def test_it_estimates_the_us_pia_for_a_covered_wage( self ):
        # the facade delegates to the US estimator (today's-dollars PIA), so the two must agree.
        self.assertEqual(
            self._pension.estimate_entitlement( Decimal( '80000' ) ),
            estimated_pia_monthly_current( Decimal( '80000' ) ) )

    def test_a_higher_wage_estimates_a_higher_benefit( self ):
        self.assertLess(
            self._pension.estimate_entitlement( Decimal( '40000' ) ),
            self._pension.estimate_entitlement( Decimal( '90000' ) ) )
