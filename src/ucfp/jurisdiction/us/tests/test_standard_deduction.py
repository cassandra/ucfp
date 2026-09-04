"""The standard deduction (`USFederalTaxEngine._standard_deduction` and `_senior_phaseout_factor`): the
base plus a per-subject age-65 bonus and senior bonus, the senior bonus phasing out linearly across the
AGI band. Exercised directly against the 2026 single figures (base 16,100; age-65 bonus 2,050; senior
bonus 6,000; phase-out 75,000 -> 175,000)."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.context import TaxContext, TaxSubject
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D      = Decimal
_SINGLE = FilingStatus.SINGLE


class StandardDeductionTests( unittest.TestCase ):

    def setUp( self ):
        self.engine   = USFederalTaxEngine( federal_2026() )
        self.standard = federal_2026().standard_deduction[ _SINGLE ]

    def _deduction( self, agi, *ages ):
        subjects = tuple( TaxSubject( age = age, birth_year = 2026 - age ) for age in ages )
        context  = TaxContext( filing_status = _SINGLE, subjects = subjects )
        return self.engine._standard_deduction( _SINGLE, context, _D( agi ) ).total

    def test_base_only_with_no_seniors( self ):
        self.assertEqual( self._deduction( '100000', 40 ), _D( '16100' ) )

    def test_one_senior_below_the_phaseout( self ):
        # base 16,100 + age-65 bonus 2,050 + full senior bonus 6,000 (AGI below 75k) = 24,150
        self.assertEqual( self._deduction( '50000', 70 ), _D( '24150' ) )

    def test_the_parts_are_split_out_base_age_65_and_senior( self ):
        subjects = ( TaxSubject( age = 70, birth_year = 1956 ), )
        context  = TaxContext( filing_status = _SINGLE, subjects = subjects )
        parts    = self.engine._standard_deduction( _SINGLE, context, _D( '50000' ) )   # below phase-out
        self.assertEqual( ( parts.base, parts.age_65, parts.senior ),
                          ( _D( '16100' ), _D( '2050' ), _D( '6000' ) ) )
        self.assertEqual( parts.total, _D( '24150' ) )

    def test_senior_bonus_phases_out_linearly( self ):
        # AGI 125k is the midpoint of [75k, 175k] -> half the 6,000 senior bonus = 3,000;
        # 16,100 + 2,050 + 3,000 = 21,150
        self.assertEqual( self._deduction( '125000', 70 ), _D( '21150' ) )

    def test_senior_bonus_fully_phased_out( self ):
        # AGI 200k >= the 175k end -> no senior bonus; 16,100 + 2,050 = 18,150
        self.assertEqual( self._deduction( '200000', 70 ), _D( '18150' ) )

    def test_phaseout_factor_boundaries( self ):
        factor = self.engine._senior_phaseout_factor
        self.assertEqual( factor( self.standard, _D( '75000' ) ), _D( '1' ) )      # at the start: full
        self.assertEqual( factor( self.standard, _D( '175000' ) ), _D( '0' ) )     # at the end: zero
        self.assertEqual( factor( self.standard, _D( '125000' ) ), _D( '0.5' ) )   # midpoint: half


if __name__ == '__main__':
    unittest.main()
