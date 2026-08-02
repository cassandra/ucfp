"""The federal SALT itemized deduction, and how the modeled state income tax (#112) enters it.

The simplified state income tax is folded into the SALT total (ledger property tax + the modeled
state income tax), together subject to the SALT cap. These exercise `_itemized_deduction` directly
with a minimal fiscal-window stub, including the case the issue fixes: at the raised (OBBBA) cap the
state income tax tips an otherwise-standard-deduction household into itemizing."""
import unittest
from decimal import Decimal

from ucfp.accounts.enums import ExpenseTaxClass
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

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


if __name__ == '__main__':
    unittest.main()
