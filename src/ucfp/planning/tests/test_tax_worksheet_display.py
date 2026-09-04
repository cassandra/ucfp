"""The tax worksheet render model: dropping all-zero columns, cell formatting, and the group / income
sub-group header spans."""
import unittest
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.tax_worksheet import (
    Column, ColumnCategory, ColumnFormat, ColumnGroup, TaxDisplayWorksheet, YearRow )
from ucfp.planning.tax_worksheet_display import build_table

_D = Decimal


def _worksheet( years ) -> TaxDisplayWorksheet:
    income = ColumnGroup( ColumnCategory.INCOME, (
        Column( 'wages', 'Wages', ColumnFormat.MONEY, subgroup = 'Earned' ),
        Column( 'int1', 'Bank Interest', ColumnFormat.MONEY, subgroup = 'Interest' ),
        Column( 'int2', 'Bond Interest', ColumnFormat.MONEY, subgroup = 'Interest' ) ) )
    taxes = ColumnGroup( ColumnCategory.TAXES, (
        Column( 'ordinary_tax', 'Ordinary Income Tax', ColumnFormat.MONEY ),
        Column( 'niit', 'NIIT', ColumnFormat.MONEY ) ) )
    rates = ColumnGroup( ColumnCategory.RATES, (
        Column( 'effective', 'Effective', ColumnFormat.RATE ), ) )
    return TaxDisplayWorksheet(
        jurisdiction = JurisdictionType.US_FEDERAL, groups = ( income, taxes, rates ), years = years )


def _year( year, ** cells ) -> YearRow:
    return YearRow( year = year, cells = cells )


class SuppressionTest( unittest.TestCase ):

    def test_a_column_zero_in_every_year_is_dropped( self ):
        # niit is 0 both years and int2 is absent both years -> both omitted; the rest stay.
        worksheet = _worksheet( (
            _year( 2030, wages = _D( '60000' ), int1 = _D( '500' ), ordinary_tax = _D( '5000' ),
                   niit = _D( '0' ), effective = _D( '0.12' ) ),
            _year( 2031, wages = _D( '61000' ), int1 = _D( '400' ), ordinary_tax = _D( '5200' ),
                   niit = _D( '0' ), effective = _D( '0.12' ) ) ) )
        labels = [ column.label for column in build_table( worksheet ).columns ]
        self.assertEqual( labels, [ 'Wages', 'Bank Interest', 'Ordinary Income Tax', 'Effective' ] )

    def test_a_column_nonzero_in_any_year_is_kept( self ):
        worksheet = _worksheet( (
            _year( 2030, wages = _D( '60000' ), niit = _D( '0' ) ),
            _year( 2031, wages = _D( '60000' ), niit = _D( '380' ) ) ) )   # niit fires only in 2031
        labels = [ column.label for column in build_table( worksheet ).columns ]
        self.assertIn( 'NIIT', labels )

    def test_an_all_zero_worksheet_is_empty( self ):
        worksheet = _worksheet( ( _year( 2030 ), _year( 2031 ) ) )         # no cells at all
        self.assertTrue( build_table( worksheet ).is_empty )


class FormattingTest( unittest.TestCase ):

    def _row( self ):
        worksheet = _worksheet( (
            _year( 2030, wages = _D( '60000.4' ), ordinary_tax = _D( '5000' ),
                   effective = _D( '0.1234' ) ), ) )
        return build_table( worksheet ).rows[ 0 ]

    def test_money_is_whole_dollars_with_separators( self ):
        self.assertEqual( self._row().cells[ 0 ], '$60,000' )              # wages, rounded

    def test_a_rate_is_a_one_decimal_percent( self ):
        self.assertEqual( self._row().cells[ -1 ], '12.3%' )              # effective

    def test_a_negative_money_value_carries_a_leading_minus( self ):
        row = build_table( _worksheet( (
            _year( 2030, wages = _D( '-1200' ), ordinary_tax = _D( '1' ) ), ) ) ).rows[ 0 ]
        self.assertEqual( row.cells[ 0 ], '-$1,200' )


class HeaderSpanTest( unittest.TestCase ):

    def _table( self ):
        return build_table( _worksheet( (
            _year( 2030, wages = _D( '60000' ), int1 = _D( '500' ), int2 = _D( '200' ),
                   ordinary_tax = _D( '5000' ), effective = _D( '0.12' ) ), ) ) )

    def test_income_is_split_into_contiguous_tax_class_subgroups( self ):
        spans = self._table().spans
        income_spans = [ ( span.label, span.colspan ) for span in spans if span.css == 'tw-cat-income' ]
        # Earned (wages) then Interest (two accounts banded together).
        self.assertEqual( income_spans, [ ( 'Earned', 1 ), ( 'Interest', 2 ) ] )

    def test_other_groups_span_under_their_category_heading( self ):
        spans = { span.css: ( span.label, span.colspan ) for span in self._table().spans }
        self.assertEqual( spans[ 'tw-cat-taxes' ], ( 'Tax Values', 1 ) )   # only ordinary_tax survived
        self.assertEqual( spans[ 'tw-cat-rates' ], ( 'Tax Rates', 1 ) )

    def test_columns_carry_their_category_color( self ):
        columns = self._table().columns
        self.assertEqual( columns[ 0 ].css, 'tw-cat-income' )
        self.assertEqual( columns[ -1 ].css, 'tw-cat-rates' )


if __name__ == '__main__':
    unittest.main()
