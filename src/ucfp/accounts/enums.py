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
    UNREALIZED_GAINS = ( 'Unrealized Gains' , 'Equity counterpart for unrealized appreciation.' )


class AssetClass( LabeledEnum ):
    """A behavior-equivalence class for asset accounts in projection.

    Each class groups asset accounts the projection treats identically -- the same
    growth, distribution, basis, and realization behavior. It is the dispatch key
    for that behavior; the behavior itself lives in the projection layer, not here.
    "Tax-free", "ordinary", etc. are *tax-treatment* classes a class maps into, a
    separate taxonomy -- so Roth is its own behavior class, not a generic
    tax-free bucket. Set on asset accounts only (see Account.asset_class).
    """

    CASH                  = ( 'Cash & Savings'          , 'Cash and savings; the income/expense hub.' )
    STOCKS                = ( 'Stocks'                  , 'Growth equities; appreciation only.' )
    DIVIDEND_STOCKS       = ( 'Dividend Stocks'         , 'Dividend equities, plus appreciation.' )
    BONDS                 = ( 'Bonds'                   , 'Bonds paying interest, with appreciation.' )
    CDS                   = ( 'CDs'                     , 'Certificates of deposit paying interest.' )
    REAL_ESTATE_RESIDENCE = ( 'Real Estate (Residence)' , 'A primary residence held for appreciation.' )
    REAL_ESTATE_RENTAL    = ( 'Real Estate (Rental)'    , 'Rental property: income and depreciation.' )
    PRETAX_RETIREMENT     = ( 'Pre-Tax Retirement'      , 'IRA/401(k); withdrawals are ordinary income.' )
    ROTH                  = ( 'Roth Retirement'         , 'Qualified withdrawals tax-free; no RMDs.' )
    PRECIOUS_METALS       = ( 'Precious Metals'         , 'Gold, silver; taxed as collectibles.' )
    COLLECTIBLES          = ( 'Collectibles'            , 'Art, jewelry and similar collectibles.' )
    DEPRECIATING          = ( 'Depreciating Assets'     , 'Vehicles, boats; depreciate over time.' )

    @property
    def accrues_unrealized_gains( self ) -> bool:
        """Whether this class accumulates unrealized gain/loss in a valuation
        companion account, rather than being held at face value."""
        return self not in _NON_APPRECIATING_ASSET_CLASSES


# Cash-like classes carried at face value: their return is distributed as interest
# income, not accrued as appreciation, so they have no valuation companion.
_NON_APPRECIATING_ASSET_CLASSES = frozenset( ( AssetClass.CASH, AssetClass.CDS ) )
