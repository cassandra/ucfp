"""Enumerations for the accounts (double-entry core) app."""
from common.labeled_enum import LabeledEnum


class SideType( LabeledEnum ):
    """A side of the double-entry ledger.

    The single Debit/Credit vocabulary, used for two distinct roles: an
    account's normal balance side (Account.account_normal_type) and the side an
    entry posts to (Entry.entry_direction).
    """

    DEBIT  = ( 'Debit'  , 'The left side of the ledger.' )
    CREDIT = ( 'Credit' , 'The right side of the ledger.' )


class AccountType( LabeledEnum ):
    """A top-level classification of accounts in double-entry bookkeeping.

    Each type has a normal balance side (see normal_side): the side on which an
    increase to the account is recorded, and on which a positive natural balance
    sits.
    """

    ASSET     = ( 'Asset'     , 'Resources owned (cash, investments, property).' )
    LIABILITY = ( 'Liability' , 'Obligations owed to others (loans, debts).' )
    EQUITY    = ( 'Equity'    , 'Residual interest: assets minus liabilities.' )
    REVENUE   = ( 'Revenue'   , 'Inflows that increase equity (income).' )
    EXPENSE   = ( 'Expense'   , 'Outflows that decrease equity (costs).' )

    @property
    def normal_side( self ) -> SideType:
        return _ACCOUNT_TYPE_NORMAL_SIDE[ self ]


# The normal balance side per account type: Assets and Expenses are debit-normal;
# Liabilities, Equity, and Revenue are credit-normal. This drives only the
# display sign of natural_balance and validation -- never the core arithmetic,
# which is uniformly credit-positive.
_ACCOUNT_TYPE_NORMAL_SIDE = {
    AccountType.ASSET     : SideType.DEBIT,
    AccountType.LIABILITY : SideType.CREDIT,
    AccountType.EQUITY    : SideType.CREDIT,
    AccountType.REVENUE   : SideType.CREDIT,
    AccountType.EXPENSE   : SideType.DEBIT,
}


class CurrencyType( LabeledEnum ):
    """ISO 4217 currencies supported for accounts and transactions.

    Seeded with a common subset. USD is the default base currency.
    """

    USD = ( 'US Dollar'         , 'United States dollar.' )
    EUR = ( 'Euro'              , 'European Union euro.' )
    GBP = ( 'British Pound'     , 'Pound sterling.' )
    JPY = ( 'Japanese Yen'      , 'Japanese yen.' )
    CAD = ( 'Canadian Dollar'   , 'Canadian dollar.' )
    AUD = ( 'Australian Dollar' , 'Australian dollar.' )
    CHF = ( 'Swiss Franc'       , 'Swiss franc.' )

    @classmethod
    def default( cls ):
        return cls.USD


class SystemAccountRole( LabeledEnum ):
    """Well-known, app-managed accounts beyond the per-type roots.

    The per-type root accounts are identified structurally (parentless, with an
    account_type), so they need no role. This enum names the other system
    accounts that initialize_chart creates and that are protected from deletion
    and closing.
    """

    OPENING_BALANCES = ( 'Opening Balances' , 'Equity counterpart for a Journal opening seed.' )
