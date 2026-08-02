"""The federal SALT itemized deduction, and how the modeled state income tax (#112) enters it.

The simplified state income tax is folded into the SALT total (ledger property tax + the modeled
state income tax), together subject to the SALT cap. These exercise `_itemized_deduction` directly
with a minimal fiscal-window stub, including the case the issue fixes: at the raised (OBBBA) cap the
state income tax tips an otherwise-standard-deduction household into itemizing."""
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

_D = Decimal


class _Window:
    """A fiscal-window stub returning fixed itemizable expenses; every unlisted class is zero.
    `_itemized_deduction` reads only expenses (medical, SALT, mortgage interest, charitable)."""

    def __init__( self, salt = _D( '0' ), medical = _D( '0' ),
                  mortgage = _D( '0' ), charitable = _D( '0' ) ):
        self._by_class = {
            ExpenseTaxClass.SALT              : salt,
            ExpenseTaxClass.MEDICAL           : medical,
            ExpenseTaxClass.MORTGAGE_INTEREST : mortgage,
            ExpenseTaxClass.CHARITABLE        : charitable,
        }

    def expense( self, expense_tax_class ):
        return self._by_class.get( expense_tax_class, _D( '0' ) )


def _itemized( salt, state_income_tax, agi = '120000', **expenses ):
    engine = USFederalTaxEngine( federal_2026() )
    window = _Window( salt = _D( salt ), **{ name : _D( value ) for name, value in expenses.items() } )
    return engine._itemized_deduction( window, _D( agi ), _D( state_income_tax ) )


class ItemizedSaltTest( unittest.TestCase ):

    def test_state_income_tax_adds_to_property_tax_below_the_cap( self ):
        # 8k property + 12k state income tax = 20k SALT, under the cap -> fully deductible.
        self.assertEqual( _itemized( '8000', '12000' ), _D( '20000' ) )

    def test_state_income_tax_is_the_whole_salt_when_there_is_no_property_tax( self ):
        self.assertEqual( _itemized( '0', '12000' ), _D( '12000' ) )

    def test_combined_salt_clamps_at_the_cap( self ):
        # 18k property + 30k state = 48k, clamped to the SALT cap.
        cap = federal_2026().itemized_rules.salt_cap
        self.assertEqual( _itemized( '18000', '30000' ), cap )

    def test_zero_state_income_tax_leaves_salt_as_property_tax_only( self ):
        # The behavior-preserving baseline: with no state income tax, SALT is unchanged.
        self.assertEqual( _itemized( '9000', '0' ), _D( '9000' ) )

    def test_state_income_tax_tips_the_household_into_itemizing( self ):
        # The materiality #112 fixes: a single filer whose property tax + mortgage interest fall just
        # under the standard deduction (so the standard would win) itemizes once the state income tax
        # joins SALT. Compared against the base standard deduction (no seniors -> no bonuses).
        engine   = USFederalTaxEngine( federal_2026() )
        standard = federal_2026().standard_deduction[ FilingStatus.SINGLE ].base
        agi      = _D( '120000' )
        window   = _Window( salt = _D( '9000' ), mortgage = _D( '4000' ) )   # 13k itemized without state tax
        without_state = engine._itemized_deduction( window, agi, _D( '0' ) )
        with_state    = engine._itemized_deduction( window, agi, _D( '15000' ) )
        self.assertLess( without_state, standard )      # standard deduction would win
        self.assertGreater( with_state, standard )      # itemizing now wins


_SPAN = SimpleNamespace( end_date = date( 2026, 12, 31 ), day_before_start = date( 2025, 12, 31 ) )


class _AssessWindow:
    """A minimal fiscal-window stub for a wage-free single filer with only ordinary income and a
    couple of itemizable expenses -- enough to drive `assess` through the deduction choice without
    holdings, gains, rentals, or Social Security (every unlisted income/expense class is zero)."""

    def __init__( self, ordinary, salt, mortgage ):
        self.span     = _SPAN
        self._income  = { IncomeTaxClass.ORDINARY : ordinary }
        self._expense = {
            ExpenseTaxClass.SALT              : salt,
            ExpenseTaxClass.MORTGAGE_INTEREST : mortgage,
        }

    def income( self, income_tax_class ):
        return self._income.get( income_tax_class, _D( '0' ) )

    def income_by_account( self, income_tax_class ):
        return []

    def expense( self, expense_tax_class ):
        return self._expense.get( expense_tax_class, _D( '0' ) )

    def holdings( self ):
        return []

    def opening_value( self, holding ):
        return _D( '0' )

    def distributions_to_cash( self, holding ):
        return _D( '0' )

    def contributions_from_cash( self, holding ):
        return _D( '0' )


def _assess_charges( state_income_tax_policy ):
    """`assess` the single-filer household through the full pipeline, returning its charges keyed by
    tax class. AGI 120k (ordinary), 9k property tax, 4k mortgage interest -- the two itemizable costs."""
    engine     = USFederalTaxEngine( federal_2026(), state_income_tax_policy )
    window     = _AssessWindow( ordinary = _D( '120000' ), salt = _D( '9000' ), mortgage = _D( '4000' ) )
    assessment = engine.assess( window, TaxContext( FilingStatus.SINGLE ), None )
    return { charge.tax_class : charge.amount for charge in assessment.charges }


class ItemizedSaltAssessTest( unittest.TestCase ):
    """End-to-end through `assess`: the single computed state-tax figure both books as the
    STATE_INCOME_TAX charge and feeds the SALT deduction, and including it flips the household from
    the standard deduction to itemizing -- lowering the federal ordinary income tax."""

    _AGI      = _D( '120000' )
    _PROPERTY = _D( '9000' )
    _MORTGAGE = _D( '4000' )

    def test_the_state_tax_charge_is_the_same_figure_that_feeds_salt_and_flips_to_itemizing( self ):
        brackets = federal_2026().ordinary_brackets[ FilingStatus.SINGLE ]
        # A 5% flat state tax with no retirement exemption -> 6,000 on 120k AGI.
        charges      = _assess_charges( StateIncomeTax( rate = Rate.percent( _D( '5' ) ) ) )
        state_charge = charges[ ExpenseTaxClass.STATE_INCOME_TAX ]
        self.assertEqual( state_charge, _D( '6000.00' ) )
        # The SAME state-tax figure joins SALT (property + state + mortgage = 19k > the 16.1k standard),
        # so the ordinary income tax is assessed on AGI minus that itemized total -- proving both the
        # reuse of the single computed value and the flip to itemizing.
        itemized = self._PROPERTY + state_charge + self._MORTGAGE
        self.assertEqual(
            charges[ ExpenseTaxClass.ORDINARY_INCOME_TAX ], brackets.tax_on( self._AGI - itemized ) )

    def test_without_state_tax_the_standard_deduction_is_taken_and_federal_tax_is_higher( self ):
        brackets = federal_2026().ordinary_brackets[ FilingStatus.SINGLE ]
        standard = federal_2026().standard_deduction[ FilingStatus.SINGLE ].base
        charges  = _assess_charges( StateIncomeTax() )   # default: no state tax
        # Property + mortgage alone (13k) fall under the standard deduction, so the standard is taken,
        # no state-income-tax charge is booked, and the ordinary income tax is higher than the itemizing
        # case above (the materiality #112 fixes: the exclusion overstated federal tax).
        self.assertNotIn( ExpenseTaxClass.STATE_INCOME_TAX, charges )
        self.assertEqual(
            charges[ ExpenseTaxClass.ORDINARY_INCOME_TAX ], brackets.tax_on( self._AGI - standard ) )


if __name__ == '__main__':
    unittest.main()
