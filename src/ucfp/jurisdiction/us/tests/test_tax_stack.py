"""`_tax_on_stack`: the rate-layer ordering follows the IRC Schedule D Tax Worksheet (issue #78).

The §1250 depreciation recapture and 28% collectibles stack *above* the preferential long-term
gain, not below it. So a high-income sale year taxes the recapture at its 25% cap (rather than the
low ordinary brackets), and the regular long-term gain keeps its low 0/15/20% brackets. This is the
subtle ordering the previous code inverted, and it had no direct test -- the two errors offset in
the total -- so it earns one now."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine, _TaxableSplit
from ucfp.jurisdiction.us.parameters import federal_2026

_MFJ = FilingStatus.MARRIED_JOINT


class TaxStackOrderingTests( unittest.TestCase ):

    def setUp( self ):
        self.parameters = federal_2026()
        self.engine     = USFederalTaxEngine( self.parameters )
        self.cap        = self.parameters.section_1250_rate

    def _stack( self, ordinary, preferential, section_1250, collectibles = '0' ):
        split = _TaxableSplit(
            Decimal( ordinary ), Decimal( preferential ),
            Decimal( section_1250 ), Decimal( collectibles ) )
        return self.engine._tax_on_stack( _MFJ, split )

    def test_recapture_hits_the_25pct_cap_above_a_large_preferential_gain( self ):
        # low ordinary income, a large long-term gain, $100k of §1250 recapture: the recapture sits
        # at the top of the stack (above the gain), where the ordinary rate exceeds 25%, so it is
        # taxed at exactly the 25% cap -- not the low ordinary brackets the inverted order gave it
        parts = self._stack( '20000', '400000', '100000' )
        self.assertEqual( parts.section_1250, self.cap * Decimal( '100000' ) )

    def test_recapture_does_not_push_up_the_preferential_gain( self ):
        # because §1250 stacks ABOVE the preferential gain, adding recapture must not change the tax
        # on the gain (the inverted order stacked the gain on top of §1250, pushing it into 20%)
        without        = self._stack( '20000', '400000', '0' )
        with_recapture = self._stack( '20000', '400000', '100000' )
        self.assertEqual( with_recapture.capital_gains, without.capital_gains )

    def test_recapture_stays_below_the_cap_when_total_income_is_low( self ):
        # §1250 as the only income fills the low ordinary brackets, so it is taxed below the 25% cap
        # -- the cap is a ceiling, not a flat rate
        parts = self._stack( '0', '0', '50000' )
        self.assertLess( parts.section_1250, self.cap * Decimal( '50000' ) )
        self.assertGreater( parts.section_1250, Decimal( '0' ) )


if __name__ == '__main__':
    unittest.main()
