"""The self-describing default memo a Realization synthesizes when the caller supplies none.

A realization means different things by the accounts it touches: proceeds to cash are a sale (or a
withdrawal, for a retirement holding), while proceeds to another holding are a conversion. This pins those
memos so a scheduled sale/withdrawal/conversion reads meaningfully in the transaction drill-down, without
threading a user label through the engine. A derived RMD passes its own reason and bypasses this.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.enums import AccountType, AssetClass
from ucfp.period.events import Realization


def _asset( name, asset_class ):
    """A holding under an asset root -- an asset_class may live only on a non-root account."""
    return Account(
        name = name, parent = Account( name = 'Assets', account_type = AccountType.ASSET ),
        asset_class = asset_class )


class RealizationDescribeTests( unittest.TestCase ):

    _CASH = _asset( 'Cash & Savings', AssetClass.CASH )

    def test_proceeds_to_cash_from_a_taxable_holding_is_a_sale( self ):
        realization = Realization(
            date( 2030, 1, 1 ), _asset( 'Brokerage', AssetClass.STOCKS ), None, self._CASH )
        self.assertEqual( realization._describe(), 'Sale of Brokerage' )

    def test_proceeds_to_cash_from_a_retirement_holding_is_a_withdrawal( self ):
        realization = Realization(
            date( 2030, 1, 1 ), _asset( 'IRA', AssetClass.PRETAX_RETIREMENT ),
            Decimal( '5000' ), self._CASH )
        self.assertEqual( realization._describe(), 'Withdrawal from IRA' )

    def test_proceeds_to_another_holding_is_a_conversion( self ):
        realization = Realization(
            date( 2030, 1, 1 ), _asset( 'IRA', AssetClass.PRETAX_RETIREMENT ),
            Decimal( '5000' ), _asset( 'Roth', AssetClass.ROTH ) )
        self.assertEqual( realization._describe(), 'Conversion of IRA to Roth' )


if __name__ == '__main__':
    unittest.main()
