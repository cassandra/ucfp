"""The self-describing default memos the scheduled events synthesize when the caller supplies none.

Each event posts to accounts a memo can name -- and several (gifts, transfers, sales) touch shared cash or
equity accounts where the source is otherwise invisible -- so an event describes itself from the accounts
it touches: a realization as a sale/withdrawal/conversion, a gift as a receipt/disbursement, a loan as an
origination/payoff, and so on. This pins those memos so a scheduled operation reads meaningfully in the
transaction drill-down, without threading a user label through the engine. A derived RMD passes its own
reason and bypasses the default.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.enums import AccountType, AssetClass
from ucfp.period.events import (
    ExternalDisbursement, ExternalReceipt, LoanOrigination, LoanPayoff, Purchase, Realization, Transfer )


def _under( root_type, name, **fields ):
    """An account under a fresh root of `root_type` (an asset_class may live only on a non-root account)."""
    return Account( name = name, parent = Account( name = 'Root', account_type = root_type ), **fields )


def _asset( name, asset_class ):
    return _under( AccountType.ASSET, name, asset_class = asset_class )


_CASH      = _asset( 'Cash & Savings', AssetClass.CASH )
_LIABILITY = _under( AccountType.LIABILITY, 'Mortgage' )
_EQUITY    = _under( AccountType.EQUITY, 'External Receipts' )


class EventDescribeTests( unittest.TestCase ):

    def test_realization_to_cash_from_a_taxable_holding_is_a_sale( self ):
        event = Realization( date( 2030, 1, 1 ), _asset( 'Brokerage', AssetClass.STOCKS ), None, _CASH )
        self.assertEqual( event._describe(), 'Sale of Brokerage' )

    def test_realization_to_cash_from_a_retirement_holding_is_a_withdrawal( self ):
        event = Realization(
            date( 2030, 1, 1 ), _asset( 'IRA', AssetClass.PRETAX_RETIREMENT ), Decimal( '5000' ), _CASH )
        self.assertEqual( event._describe(), 'Withdrawal from IRA' )

    def test_realization_to_another_holding_is_a_conversion( self ):
        event = Realization(
            date( 2030, 1, 1 ), _asset( 'IRA', AssetClass.PRETAX_RETIREMENT ), Decimal( '5000' ),
            _asset( 'Roth', AssetClass.ROTH ) )
        self.assertEqual( event._describe(), 'Conversion of IRA to Roth' )

    def test_transfer_names_both_ends( self ):
        event = Transfer( date( 2030, 1, 1 ), _CASH, _asset( 'CD Ladder', AssetClass.CDS ), Decimal( '1' ) )
        self.assertEqual( event._describe(), 'Transfer from Cash & Savings to CD Ladder' )

    def test_external_receipt_reads_as_a_gift_or_inheritance( self ):
        event = ExternalReceipt( date( 2030, 1, 1 ), _CASH, _EQUITY, Decimal( '1' ) )
        self.assertEqual( event._describe(), 'Gift or inheritance received into Cash & Savings' )

    def test_external_disbursement_reads_as_a_personal_gift( self ):
        event = ExternalDisbursement( date( 2030, 1, 1 ), _CASH, _EQUITY, Decimal( '1' ) )
        self.assertEqual( event._describe(), 'Personal gift given from Cash & Savings' )

    def test_loan_payoff_names_the_loan( self ):
        event = LoanPayoff( date( 2030, 1, 1 ), _LIABILITY, _CASH )
        self.assertEqual( event._describe(), 'Payoff of Mortgage' )

    def test_loan_origination_names_the_loan( self ):
        event = LoanOrigination( date( 2030, 1, 1 ), _LIABILITY, _CASH, Decimal( '1' ) )
        self.assertEqual( event._describe(), 'Origination of Mortgage' )

    def test_purchase_names_the_asset_and_funding( self ):
        event = Purchase( date( 2030, 1, 1 ), _CASH, _asset( 'Boat', AssetClass.DEPRECIATING ), Decimal( '1' ) )
        self.assertEqual( event._describe(), 'Purchase of Boat funded from Cash & Savings' )


if __name__ == '__main__':
    unittest.main()
