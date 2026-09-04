"""The tax worksheet render model: dropping all-zero columns, the owner-only income labels (so a column
does not repeat its tax-class sub-group heading), cell formatting, and the header spans."""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.tax_worksheet import (
    Column, ColumnCategory, ColumnFormat, ColumnGroup, TaxDisplayWorksheet, YearRow )
from ucfp.planning.tax_worksheet_display import build_table

_D = Decimal


def _worksheet( years ) -> TaxDisplayWorksheet:
    income = ColumnGroup( ColumnCategory.INCOME, (
        Column( 'w_john', 'John Wages', ColumnFormat.MONEY, subgroup = 'Wages' ),
        Column( 'w_jane', 'Jane Wages', ColumnFormat.MONEY, subgroup = 'Wages' ),
        Column( 'interest', 'Taxable Interest', ColumnFormat.MONEY, subgroup = 'Taxable Interest' ) ) )
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
        worksheet = _worksheet( (
            _year( 2030, w_john = _D( '60000' ), ordinary_tax = _D( '5000' ), niit = _D( '0' ) ),
            _year( 2031, w_john = _D( '61000' ), ordinary_tax = _D( '5200' ), niit = _D( '0' ) ) ) )
        labels = [ column.label for column in build_table( worksheet ).columns ]
        self.assertIn( 'Ordinary Income Tax', labels )
        self.assertNotIn( 'NIIT', labels )                               # zero every year -> dropped

    def test_a_column_nonzero_in_any_year_is_kept( self ):
        worksheet = _worksheet( (
            _year( 2030, w_john = _D( '60000' ), niit = _D( '0' ) ),
            _year( 2031, w_john = _D( '60000' ), niit = _D( '380' ) ) ) )
        self.assertIn( 'NIIT', [ column.label for column in build_table( worksheet ).columns ] )

    def test_an_all_zero_worksheet_is_empty( self ):
        self.assertTrue( build_table( _worksheet( ( _year( 2030 ), _year( 2031 ) ) ) ).is_empty )


class ColumnLabelTest( unittest.TestCase ):

    def _columns( self ):
        worksheet = _worksheet( (
            _year( 2030, w_john = _D( '90000' ), w_jane = _D( '50000' ), interest = _D( '500' ),
                   ordinary_tax = _D( '5000' ), effective = _D( '0.12' ) ), ) )
        return build_table( worksheet ).columns

    def test_an_income_column_shows_the_owner_not_the_repeated_tax_class( self ):
        # Under the 'Wages' sub-group span, the columns show only 'John' / 'Jane', not 'John Wages'.
        self.assertEqual( [ column.label for column in self._columns()[ :2 ] ], [ 'John', 'Jane' ] )

    def test_the_sole_account_of_its_class_has_a_blank_label( self ):
        # 'Taxable Interest' is the only account of its class, so the span already names it -> blank column.
        self.assertEqual( self._columns()[ 2 ].label, '' )

    def test_a_non_income_column_keeps_its_full_label( self ):
        labels = [ column.label for column in self._columns() ]
        self.assertIn( 'Ordinary Income Tax', labels )
        self.assertIn( 'Effective', labels )


class FormattingTest( unittest.TestCase ):

    def _row( self ):
        worksheet = _worksheet( (
            _year( 2030, w_john = _D( '60000.4' ), ordinary_tax = _D( '5000' ),
                   effective = _D( '0.1234' ) ), ) )
        return build_table( worksheet ).rows[ 0 ]

    def test_money_is_whole_dollars_with_separators( self ):
        self.assertEqual( self._row().cells[ 0 ], '$60,000' )

    def test_a_rate_is_a_one_decimal_percent( self ):
        self.assertEqual( self._row().cells[ -1 ], '12.3%' )

    def test_a_negative_money_value_carries_a_leading_minus( self ):
        row = build_table( _worksheet( (
            _year( 2030, w_john = _D( '-1200' ), ordinary_tax = _D( '1' ) ), ) ) ).rows[ 0 ]
        self.assertEqual( row.cells[ 0 ], '-$1,200' )


class AgeColumnTest( unittest.TestCase ):

    def test_each_row_carries_the_primary_subjects_age_that_year( self ):
        worksheet = _worksheet( ( _year( 2030, w_john = _D( '60000' ) ),
                                  _year( 2031, w_john = _D( '61000' ) ) ) )
        rows = build_table( worksheet, date( 1962, 6, 15 ) ).rows   # age at year-end = year - birth year
        self.assertEqual( [ ( row.year, row.age ) for row in rows ], [ ( 2030, 68 ), ( 2031, 69 ) ] )

    def test_age_is_none_without_a_birthdate( self ):
        worksheet = _worksheet( ( _year( 2030, w_john = _D( '60000' ) ), ) )
        self.assertIsNone( build_table( worksheet ).rows[ 0 ].age )


class HeaderSpanTest( unittest.TestCase ):

    def _table( self ):
        return build_table( _worksheet( (
            _year( 2030, w_john = _D( '90000' ), w_jane = _D( '50000' ), interest = _D( '500' ),
                   ordinary_tax = _D( '5000' ), effective = _D( '0.12' ) ), ) ) )

    def test_income_is_split_into_contiguous_tax_class_subgroups( self ):
        income_spans = [ ( span.label, span.colspan ) for span in self._table().spans
                         if span.css == 'tw-cat-income' ]
        self.assertEqual( income_spans, [ ( 'Wages', 2 ), ( 'Taxable Interest', 1 ) ] )

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
