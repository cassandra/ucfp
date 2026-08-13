"""Employee employment tax -- US FICA (`USFederalTaxEngine._employment_tax`): Social Security on each
worker's wages up to the wage base (capped per worker), Medicare on all wages, plus the Additional Medicare surtax on
combined wages over the filing-status threshold. Exercised directly with a per-worker wage stub against
the 2026 rules (SS 6.2% to 184,500; Medicare 1.45%; surtax 0.9% over 200k single / 250k joint)."""
import unittest
from decimal import Decimal

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D = Decimal


class _Window:
    """A fiscal-window stub exposing per-worker WAGES (the only thing `_employment_tax` reads); every
    other class is empty."""

    def __init__( self, *worker_wages ):
        self._wages = [ _D( wage ) for wage in worker_wages ]

    def income_by_account( self, income_tax_class ):
        return self._wages if income_tax_class == IncomeTaxClass.WAGES else []


class EmploymentTaxTests( unittest.TestCase ):

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )

    def _employment( self, status, *worker_wages ):
        return self.engine._employment_tax( status, _Window( *worker_wages ) )

    def test_below_wage_base_and_surtax_threshold( self ):
        # single, 100k wages: SS 6.2% = 6,200; Medicare 1.45% = 1,450; no surtax -> 7,650
        self.assertEqual( self._employment( FilingStatus.SINGLE, '100000' ), _D( '7650' ) )

    def test_ss_capped_at_the_wage_base_plus_the_additional_medicare_surtax( self ):
        # single, 300k: SS 6.2% of 184,500 = 11,439; Medicare 1.45% of 300k = 4,350;
        # surtax 0.9% of (300k - 200k) = 900 -> 16,689
        self.assertEqual( self._employment( FilingStatus.SINGLE, '300000' ), _D( '16689' ) )

    def test_social_security_cap_is_per_worker( self ):
        # married joint, two earners each at the 184,500 wage base: two separate SS caps
        # (2 x 11,439 = 22,878); Medicare 1.45% of 369,000 = 5,350.50; surtax 0.9% of (369k - 250k) = 1,071
        self.assertEqual(
            self._employment( FilingStatus.MARRIED_JOINT, '184500', '184500' ), _D( '29299.50' ) )


if __name__ == '__main__':
    unittest.main()
