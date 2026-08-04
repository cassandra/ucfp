"""MoneyField parses a thousands-grouped value.

The money input is a text field carrying commas as the user types (inputs.js groups them), so the
field must strip the separators before the decimal parse -- otherwise a grouped "122,000" fails to
validate.
"""
import unittest
from decimal import Decimal

from common.forms import MoneyField


class MoneyFieldParsingTests( unittest.TestCase ):

    def test_strips_thousands_separators( self ):
        self.assertEqual( MoneyField().clean( '122,000' ), Decimal( '122000' ) )

    def test_strips_separators_with_a_decimal_part( self ):
        self.assertEqual( MoneyField().clean( '1,234,567.89' ), Decimal( '1234567.89' ) )

    def test_plain_number_is_unaffected( self ):
        self.assertEqual( MoneyField().clean( '500' ), Decimal( '500' ) )

    def test_blank_optional_field_is_none( self ):
        self.assertIsNone( MoneyField( required = False ).clean( '' ) )
