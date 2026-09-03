"""The neutral tax display worksheet model: construction, immutability, and the enum name-stability the
persistence codec relies on (it serializes enums by name)."""
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.tax_worksheet import (
    Column, ColumnCategory, ColumnFormat, ColumnGroup, TaxDisplayWorksheet, YearRow )


def _worksheet() -> TaxDisplayWorksheet:
    income = ColumnGroup(
        category = ColumnCategory.INCOME,
        columns  = (
            Column( 'wages', 'Wages', ColumnFormat.MONEY, subgroup = 'Earned' ),
            Column( 'interest', 'Interest', ColumnFormat.MONEY, subgroup = 'Investment' ) ) )
    rates = ColumnGroup(
        category = ColumnCategory.RATES,
        columns  = ( Column( 'effective', 'Effective', ColumnFormat.RATE ), ) )
    year = YearRow(
        year  = 2030,
        cells = { 'wages': Decimal( '80000' ), 'interest': Decimal( '0' ),
                  'effective': Decimal( '0.14' ) } )
    return TaxDisplayWorksheet(
        jurisdiction = JurisdictionType.US_FEDERAL, groups = ( income, rates ), years = ( year, ) )


class ModelTest( unittest.TestCase ):

    def test_the_worksheet_holds_its_schema_and_year_rows( self ):
        worksheet = _worksheet()
        self.assertEqual( worksheet.jurisdiction, JurisdictionType.US_FEDERAL )
        self.assertEqual( [ group.category for group in worksheet.groups ],
                          [ ColumnCategory.INCOME, ColumnCategory.RATES ] )
        self.assertEqual( worksheet.years[ 0 ].cells[ 'wages' ], Decimal( '80000' ) )

    def test_a_column_carries_its_format_and_optional_subgroup( self ):
        wages, interest = _worksheet().groups[ 0 ].columns
        self.assertEqual( wages.format, ColumnFormat.MONEY )
        self.assertEqual( ( wages.subgroup, interest.subgroup ), ( 'Earned', 'Investment' ) )
        self.assertIsNone( _worksheet().groups[ 1 ].columns[ 0 ].subgroup )   # a rate has no subgroup

    def test_the_worksheet_is_immutable( self ):
        with self.assertRaises( FrozenInstanceError ):
            _worksheet().years = ()

    def test_a_missing_cell_reads_as_not_applicable( self ):
        # A key absent from a year's cells is 'not applicable that year' -- the renderer shows a blank.
        year = _worksheet().years[ 0 ]
        self.assertIsNone( year.cells.get( 'niit' ) )


class CategoryLabelTest( unittest.TestCase ):

    def test_categories_carry_their_group_headings_in_render_order( self ):
        self.assertEqual(
            [ category.label for category in ColumnCategory ],
            [ 'Income Accounts', 'Income Calculations', 'Tax Values', 'Tax Rates' ] )

    def test_enums_round_trip_by_name( self ):
        # The persistence codec serializes an enum as its .name and rebuilds it by name; guard that contract.
        self.assertIs( ColumnCategory[ 'INCOME' ], ColumnCategory.INCOME )
        self.assertIs( ColumnFormat[ 'MONEY' ], ColumnFormat.MONEY )


if __name__ == '__main__':
    unittest.main()
