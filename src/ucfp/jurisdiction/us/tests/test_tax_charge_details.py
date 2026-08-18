"""Each income-tax charge `assess` returns carries a `detail` memo scoped to its own rate layer's
drivers (mirroring `TaxPenalty.reason`), so the Period can post it as the accrual's description and
the results drill-down explains the tax rather than showing a blank memo.

One rich single-filer assessment exercises every layer at once -- ordinary income, a §1250
depreciation recapture, preferential long-term gains + qualified dividends, 28% collectibles, the
3.8% NIIT (AGI well over the single threshold), and a flat state income tax -- and each layer's memo
is asserted to surface that layer's own figures. The §1250 recapture is fed via the `SECTION_1250_GAIN`
income line (the engine-level equivalent of a rental disposition's recaptured depreciation); the
end-to-end rental-sale path is covered at the forecast level in
`ucfp/forecast/tests/test_property_sale_recapture.py`.
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.rate import Rate

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026
from ucfp.jurisdiction.us.subdivision_tax import StateIncomeTax

_D    = Decimal
_SPAN = SimpleNamespace( end_date = date( 2026, 12, 31 ), day_before_start = date( 2025, 12, 31 ) )


class _Window:
    """A fiscal-window stub returning fixed income by tax-class (every unlisted class is zero) and no
    expenses, holdings, or contributions -- enough to drive `assess` through every rate layer without
    building real books."""

    def __init__( self, income ):
        self.span    = _SPAN
        self._income = income

    def income( self, income_tax_class ):
        return self._income.get( income_tax_class, _D( '0' ) )

    def income_by_account( self, income_tax_class ):
        return []

    def expense( self, expense_tax_class ):
        return _D( '0' )

    def holdings( self ):
        return []

    def opening_value( self, holding ):
        return _D( '0' )

    def distributions_to_cash( self, holding ):
        return _D( '0' )

    def contributions_from_cash( self, holding ):
        return _D( '0' )


class TaxChargeDetailTests( unittest.TestCase ):
    """The per-layer `detail` memos on the charges `assess` returns."""

    # A single filer with ordinary income, a §1250 recapture, preferential gains + qualified dividends,
    # collectibles, and taxable interest -- AGI (435,000) is far over the 200,000 single NIIT threshold,
    # so every layer, NIIT included, produces a positive charge with a memo. A 5% flat state tax (no
    # exemptions) books the STATE_INCOME_TAX layer too.
    _INCOME = {
        IncomeTaxClass.ORDINARY            : _D( '250000' ),
        IncomeTaxClass.TAXABLE_INTEREST    : _D( '10000' ),
        IncomeTaxClass.QUALIFIED_DIVIDENDS : _D( '20000' ),
        IncomeTaxClass.LONG_TERM_GAINS     : _D( '100000' ),
        IncomeTaxClass.SECTION_1250_GAIN   : _D( '40000' ),
        IncomeTaxClass.COLLECTIBLES_GAINS  : _D( '15000' ),
    }

    def setUp( self ):
        engine     = USFederalTaxEngine(
            federal_2026(), StateIncomeTax( rate = Rate( _D( '0.05' ) ) ) )
        assessment = engine.assess(
            _Window( self._INCOME ), TaxContext( FilingStatus.SINGLE ), None )
        self.details = { charge.tax_class : charge.detail for charge in assessment.charges }

    def test_every_layer_carries_a_nonblank_detail( self ):
        # Every posted charge is explained -- no blank memo slips through.
        for tax_class, detail in self.details.items():
            self.assertTrue( detail, f'{tax_class} charge has a blank detail' )

    def test_ordinary_layer_names_agi_and_the_deduction( self ):
        detail = self.details[ ExpenseTaxClass.ORDINARY_INCOME_TAX ]
        self.assertIn( 'ordinary taxable income', detail )
        self.assertIn( 'AGI $435,000.00', detail )         # AGI is deduction-independent, so exact
        self.assertIn( 'deduction', detail )

    def test_capital_gains_layer_names_the_preferential_base( self ):
        # preferential = 20,000 qualified dividends + 100,000 net long-term gain
        detail = self.details[ ExpenseTaxClass.CAPITAL_GAINS_TAX ]
        self.assertIn( '$120,000.00', detail )
        self.assertIn( 'long-term gains and qualified dividends', detail )

    def test_section_1250_layer_names_the_recapture_and_the_25pct_rate( self ):
        detail = self.details[ ExpenseTaxClass.SECTION_1250_TAX ]
        self.assertIn( 'Recapture', detail )
        self.assertIn( '$40,000.00', detail )
        self.assertIn( '25%', detail )

    def test_collectibles_layer_names_the_gain_and_the_28pct_rate( self ):
        detail = self.details[ ExpenseTaxClass.COLLECTIBLES_TAX ]
        self.assertIn( '$15,000.00', detail )
        self.assertIn( '28%', detail )

    def test_niit_layer_surfaces_the_rate_the_nii_and_the_threshold( self ):
        # 3.8% on the lesser of 185,000 net investment income and 235,000 MAGI-over-threshold -> 185,000.
        detail = self.details[ ExpenseTaxClass.NIIT ]
        self.assertIn( '3.8%', detail )
        self.assertIn( '$185,000.00', detail )                     # the taxed amount (the lesser)
        self.assertIn( 'net investment income', detail )
        self.assertIn( 'MAGI $435,000.00', detail )
        self.assertIn( '$200,000.00 threshold', detail )

    def test_state_layer_names_the_agi_base( self ):
        detail = self.details[ ExpenseTaxClass.STATE_INCOME_TAX ]
        self.assertIn( 'State income tax on $435,000.00 AGI', detail )


class PremiumCreditDetailTest( unittest.TestCase ):
    """The refundable ACA premium tax credit carries its own MAGI-scoped detail."""

    def test_premium_credit_names_its_magi( self ):
        from ucfp.jurisdiction.subsidized_health import SubsidizedHealthEnrollment

        # A modest-income enrolled household: low enough AGI that the benchmark premium exceeds the
        # expected contribution, so a positive (refundable) credit is booked.
        enrollment = SubsidizedHealthEnrollment(
            household_size    = 1,
            reference_premium = _D( '9000' ),
            actual_premium    = _D( '9000' ) )
        context    = TaxContext( FilingStatus.SINGLE, health_enrollment = enrollment )
        engine     = USFederalTaxEngine( federal_2026() )
        assessment = engine.assess(
            _Window( { IncomeTaxClass.ORDINARY : _D( '30000' ) } ), context, None )
        credit = assessment.credits[ 0 ]
        self.assertEqual( credit.tax_class, ExpenseTaxClass.ORDINARY_INCOME_TAX )
        self.assertIn( 'ACA premium tax credit at $30,000.00 MAGI', credit.detail )


if __name__ == '__main__':
    unittest.main()
