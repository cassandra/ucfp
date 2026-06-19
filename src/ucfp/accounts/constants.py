"""Shared constants for the accounts app."""
from .enums import AccountType


# Default display names for the auto-created per-type root accounts. Defined once
# here so initialize_chart and any chart presentation draw on a single source.
# (These intentionally differ from the AccountType labels, e.g. Revenue -> Income;
# the Opening Balances account name instead derives from its SystemAccountRole.)
DEFAULT_ROOT_ACCOUNT_NAMES = {
    AccountType.ASSET     : 'Assets',
    AccountType.LIABILITY : 'Liabilities',
    AccountType.EQUITY    : 'Equity',
    AccountType.REVENUE   : 'Income',
    AccountType.EXPENSE   : 'Expenses',
}

# Default description for the auto-generated opening-balances transaction.
OPENING_TRANSACTION_DESCRIPTION = 'Opening balances'

# Decimal scale (digits, places) for monetary amounts -- finer than cents for
# planning headroom. Each Entry stores its magnitude at this scale in the
# organization's single currency (the ledger is single-currency).
MONEY_MAX_DIGITS = 19
MONEY_DECIMAL_PLACES = 5
