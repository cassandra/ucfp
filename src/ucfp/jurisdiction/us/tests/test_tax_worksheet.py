"""The US federal tax display worksheet: the builder's derivations (taxable-SS share, marginal/effective
rates, bracket headroom) and income-column grouping, plus that `assess` attaches a worksheet."""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.jurisdiction.brackets import BracketTable
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType
from ucfp.jurisdiction.tax_worksheet import ColumnCategory, ColumnFormat
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026
from ucfp.jurisdiction.us.tax_worksheet import TaxYearInputs, build_worksheet

_D = Decimal

_ORDINARY = BracketTable( (
    ( _D( '0' ), _D( '0.10' ) ), ( _D( '10000' ), _D( '0.12' ) ),
    ( _D( '40000' ), _D( '0.22' ) ), ( _D( '100000' ), _D( '0.24' ) ) ) )
_LTCG = BracketTable( (
    ( _D( '0' ), _D( '0' ) ), ( _D( '50000' ), _D( '0.15' ) ), ( _D( '500000' ), _D( '0.20' ) ) ) )


def _account( tax_class, name, handle ):
    return SimpleNamespace( income_tax_class = tax_class, name = name, handle = handle )


def _inputs( ** overrides ) -> TaxYearInputs:
    base = dict(
        year = 2030, ordinary_brackets = _ORDINARY, ltcg_brackets = _LTCG,
        niit_threshold = _D( '200000' ), income_accounts = [],
        provisional_income = _D( '44000' ), ss_gross = _D( '40000' ), taxable_ss = _D( '34000' ),
        agi = _D( '90000' ), taxable_long_term_gains = _D( '20000' ),
        net_investment_income = _D( '20500' ), standard_deduction = _D( '15000' ),
        applied_deduction = _D( '15000' ),
        taxable_ordinary_income = _D( '30000' ), taxable_income = _D( '50000' ),
        niit_magi = _D( '210000' ), ordinary_tax = _D( '3000' ), capital_gains_tax = _D( '3000' ),
        section_1250_tax = _D( '0' ), collectibles_tax = _D( '0' ), niit = _D( '380' ),
        state_income_tax = _D( '1620' ), total_tax = _D( '8000' ) )
    base.update( overrides )
    return TaxYearInputs( ** base )


def _cells( worksheet ) -> dict:
    return worksheet.years[ 0 ].cells


class DerivedColumnTest( unittest.TestCase ):

    def test_taxable_social_security_share( self ):
        cells = _cells( build_worksheet( _inputs() ) )
        self.assertEqual( cells[ 'taxable_ss_pct' ], _D( '0.85' ) )        # 34000 / 40000

    def test_a_zero_base_share_is_not_applicable_not_a_division_error( self ):
        cells = _cells( build_worksheet( _inputs( ss_gross = _D( '0' ), taxable_ss = _D( '0' ) ) ) )
        self.assertIsNone( cells[ 'taxable_ss_pct' ] )

    def test_effective_rate_is_total_over_taxable_income( self ):
        cells = _cells( build_worksheet( _inputs() ) )
        self.assertEqual( cells[ 'effective' ], _D( '0.16' ) )            # 8000 / 50000

    def test_effective_rate_with_no_taxable_income_is_not_applicable( self ):
        cells = _cells( build_worksheet( _inputs( taxable_income = _D( '0' ) ) ) )
        self.assertIsNone( cells[ 'effective' ] )

    def test_marginal_rates_read_the_bracket_at_the_income_position( self ):
        cells = _cells( build_worksheet( _inputs() ) )
        self.assertEqual( cells[ 'marginal_ordinary' ], _D( '0.12' ) )    # 30000 is in the 12% bracket
        # Gains stack on ordinary: 30000 + 20000 = 50000, the start of the 15% preferential bracket.
        self.assertEqual( cells[ 'marginal_cap_gains' ], _D( '0.15' ) )

    def test_ordinary_bracket_headroom_is_room_to_the_next_bracket( self ):
        cells = _cells( build_worksheet( _inputs() ) )
        self.assertEqual( cells[ 'headroom_ordinary' ], _D( '10000' ) )   # 40000 ceiling - 30000

    def test_niit_headroom_floors_at_zero_when_already_over( self ):
        cells = _cells( build_worksheet( _inputs() ) )                    # MAGI 210000 > 200000 threshold
        self.assertEqual( cells[ 'headroom_niit' ], _D( '0' ) )
        under = _cells( build_worksheet( _inputs( niit_magi = _D( '150000' ) ) ) )
        self.assertEqual( under[ 'headroom_niit' ], _D( '50000' ) )

    def test_the_standard_and_applied_deductions_are_both_shown( self ):
        # The standard deduction is always shown as a projected reference; the applied deduction is the one
        # actually used (the larger of standard and itemized). They coincide unless itemizing wins.
        cells = _cells( build_worksheet(
            _inputs( standard_deduction = _D( '15000' ), applied_deduction = _D( '22000' ) ) ) )
        self.assertEqual( cells[ 'standard_deduction' ], _D( '15000' ) )
        self.assertEqual( cells[ 'applied_deduction' ], _D( '22000' ) )

    def test_top_bracket_headroom_is_not_applicable( self ):
        cells = _cells( build_worksheet( _inputs( taxable_ordinary_income = _D( '250000' ) ) ) )
        self.assertIsNone( cells[ 'headroom_ordinary' ] )                 # in the open-ended top bracket


class IncomeColumnTest( unittest.TestCase ):

    def _worksheet( self ):
        accounts = [
            ( _account( IncomeTaxClass.TAX_EXEMPT_INTEREST, 'Muni Fund', 'm1' ), _D( '300' ) ),
            ( _account( IncomeTaxClass.WAGES, 'Wages — Alice', 'w1' ), _D( '60000' ) ),
            ( _account( IncomeTaxClass.TAX_FREE, 'Gift', 'g1' ), _D( '999' ) ),
            ( _account( IncomeTaxClass.TAXABLE_INTEREST, 'Bank Interest', 'i1' ), _D( '500' ) ) ]
        return build_worksheet( _inputs( income_accounts = accounts ) )

    def test_income_columns_are_ordered_by_tax_class_and_carry_the_class_subgroup( self ):
        income = self._worksheet().groups[ 0 ]
        self.assertEqual( income.category, ColumnCategory.INCOME )
        # Wages (earned) first, then taxable interest, then tax-exempt interest last; tax-free is dropped.
        self.assertEqual( [ column.label for column in income.columns ],
                          [ 'Wages — Alice', 'Bank Interest', 'Muni Fund' ] )
        self.assertEqual( [ column.subgroup for column in income.columns ],
                          [ 'Wages', 'Taxable Interest', 'Tax-Exempt Interest' ] )

    def test_income_cells_key_on_the_account_handle( self ):
        cells = _cells( self._worksheet() )
        self.assertEqual( cells[ 'income:w1' ], _D( '60000' ) )
        self.assertNotIn( 'income:g1', cells )                            # tax-free account excluded


class WorksheetShapeTest( unittest.TestCase ):

    def test_the_four_groups_are_present_in_order( self ):
        worksheet = build_worksheet( _inputs() )
        self.assertEqual( worksheet.jurisdiction, JurisdictionType.US_FEDERAL )
        self.assertEqual( [ group.category for group in worksheet.groups ],
                          [ ColumnCategory.INCOME, ColumnCategory.INCOME_DERIVED,
                            ColumnCategory.TAXES, ColumnCategory.RATES ] )

    def test_rate_columns_are_formatted_as_rates( self ):
        rates = build_worksheet( _inputs() ).groups[ 3 ]
        by_key = { column.key: column.format for column in rates.columns }
        self.assertEqual( by_key[ 'marginal_ordinary' ], ColumnFormat.RATE )
        self.assertEqual( by_key[ 'effective' ], ColumnFormat.RATE )


_SPAN = SimpleNamespace( end_date = date( 2026, 12, 31 ), day_before_start = date( 2025, 12, 31 ) )


class _Window:
    """A minimal fiscal-window stub: fixed income by class and one income account, no expenses/holdings --
    enough to drive `assess` and read the worksheet it attaches."""

    def __init__( self, income, accounts ):
        self.span     = _SPAN
        self._income  = income
        self._accounts = accounts

    def income( self, income_tax_class ):
        return self._income.get( income_tax_class, _D( '0' ) )

    def income_by_account( self, income_tax_class ):
        return []

    def income_accounts( self ):
        return self._accounts

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


class AssessAttachesWorksheetTest( unittest.TestCase ):

    def test_assess_returns_a_worksheet_for_the_year( self ):
        window = _Window(
            { IncomeTaxClass.ORDINARY: _D( '120000' ) },
            [ ( _account( IncomeTaxClass.ORDINARY, 'Pension', 'p1' ), _D( '120000' ) ) ] )
        assessment = USFederalTaxEngine( federal_2026() ).assess(
            window, TaxContext( FilingStatus.SINGLE ), None )
        self.assertIsNotNone( assessment.worksheet )
        worksheet = assessment.worksheet
        self.assertEqual( worksheet.jurisdiction, JurisdictionType.US_FEDERAL )
        self.assertEqual( len( worksheet.years ), 1 )
        self.assertEqual( worksheet.years[ 0 ].year, 2026 )
        cells = worksheet.years[ 0 ].cells
        self.assertGreater( cells[ 'agi' ], _D( '0' ) )
        self.assertEqual( cells[ 'income:p1' ], _D( '120000' ) )          # the income account column
        self.assertGreater( cells[ 'total_tax' ], _D( '0' ) )


if __name__ == '__main__':
    unittest.main()
