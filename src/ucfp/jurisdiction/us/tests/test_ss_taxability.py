"""The Social Security taxability worksheet (`USFederalTaxEngine._taxable_social_security`): the IRS
two-tier provisional-income rule -- nothing below the base threshold, up to 50% of the excess between
base and additional, up to 85% above, capped at 85% of benefits. Exercised directly with hand-computed
values against the 2026 single thresholds (base 25,000, additional 34,000)."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D      = Decimal
_SINGLE = FilingStatus.SINGLE


class SocialSecurityTaxabilityTests( unittest.TestCase ):

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )

    def _taxable( self, ss_gross, other_income ):
        return self.engine._taxable_social_security( _SINGLE, _D( ss_gross ), _D( other_income ) )

    def test_below_the_base_threshold_none_is_taxable( self ):
        # provisional = 10,000 other + 10,000 (half of 20k benefits) = 20,000 < 25,000 base
        self.assertEqual( self._taxable( '20000', '10000' ), _D( '0' ) )

    def test_middle_tier_includes_half_the_excess_over_base( self ):
        # provisional = 20,000 + 10,000 = 30,000, between 25k and 34k -> 50% of (30k - 25k) = 2,500
        self.assertEqual( self._taxable( '20000', '20000' ), _D( '2500' ) )

    def test_top_tier_below_the_85pct_cap( self ):
        # provisional = 38,000 + 10,000 = 48,000 > 34k. lower tier = min(10,000, 50% of 9,000) = 4,500;
        # upper tier = 85% of (48,000 - 34,000) = 11,900; sum 16,400 < the 85%-of-benefits cap (17,000)
        self.assertEqual( self._taxable( '20000', '38000' ), _D( '16400' ) )

    def test_top_tier_capped_at_85pct_of_benefits( self ):
        # provisional = 50,000 + 10,000 = 60,000; 4,500 + 85% of 26,000 (22,100) = 26,600,
        # capped at 85% of the 20,000 benefit = 17,000
        self.assertEqual( self._taxable( '20000', '50000' ), _D( '17000' ) )


if __name__ == '__main__':
    unittest.main()
