"""The net investment income tax (`USFederalTaxEngine._net_investment_income_tax`): 3.8% of the lesser
of net investment income and MAGI over the filing-status threshold, zero below it. Exercised directly
against the 2026 single threshold (200,000) and rate (3.8%)."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D      = Decimal
_SINGLE = FilingStatus.SINGLE


class NetInvestmentIncomeTaxTests( unittest.TestCase ):

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )

    def _niit( self, magi, net_investment_income ):
        return self.engine._net_investment_income_tax( _SINGLE, _D( magi ), _D( net_investment_income ) )

    def test_no_tax_below_the_magi_threshold( self ):
        self.assertEqual( self._niit( '150000', '50000' ), _D( '0' ) )

    def test_taxes_net_investment_income_when_it_is_the_lesser( self ):
        # magi 300k -> excess 100k; nii 40k is the lesser -> 3.8% of 40,000 = 1,520
        self.assertEqual( self._niit( '300000', '40000' ), _D( '1520' ) )

    def test_taxes_the_magi_excess_when_it_is_the_lesser( self ):
        # magi 210k -> excess 10k is the lesser -> 3.8% of 10,000 = 380
        self.assertEqual( self._niit( '210000', '50000' ), _D( '380' ) )


if __name__ == '__main__':
    unittest.main()
