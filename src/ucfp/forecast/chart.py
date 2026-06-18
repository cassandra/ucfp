"""Projection chart-of-accounts navigation and realization over a Ledger.

The Ledger is generic double-entry; the projection's chart conventions live here,
where they are valid (the projection builds the chart): a single cash hub, the
Unrealized Gains equity account, valuation companions, the cost/valuation split,
and income/expense accounts keyed by tax-class. Period and PeriodEvent share these
helpers; each takes a Ledger and uses only its generic accessors (`accounts`,
`natural_balance`, `record`).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SystemAccountRole,
)
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.models import Account
from ucfp.accounts.money_utils import quantize_money

from .exceptions import MissingAccountError


def holdings( ledger : Ledger ) -> list[ Account ]:
    """The asset holdings -- accounts carrying an asset_class (valuation companions
    and other accounts excluded)."""
    return [ account for account in ledger.accounts() if account.asset_class is not None ]


def valuation_of( ledger : Ledger, holding : Account ) -> Optional[ Account ]:
    """The holding's valuation companion (its is_valuation child), or None."""
    for account in ledger.accounts():
        if ( account.parent_id == holding.pk ) and account.is_valuation:
            return account
        continue
    return None


def system_account( ledger : Ledger, role : SystemAccountRole ) -> Optional[ Account ]:
    """The account bearing system role `role`, or None."""
    for account in ledger.accounts():
        if account.system_role == role:
            return account
        continue
    return None


def cash_account( ledger : Ledger ) -> Optional[ Account ]:
    """The cash hub: the first asset account classed CASH (multiple cash accounts
    are not yet supported), or None."""
    for account in ledger.accounts():
        if account.asset_class == AssetClass.CASH:
            return account
        continue
    return None


def income_account( ledger : Ledger, income_tax_class : IncomeTaxClass ) -> Optional[ Account ]:
    """The first revenue account with `income_tax_class`, or None."""
    for account in ledger.accounts():
        if account.income_tax_class == income_tax_class:
            return account
        continue
    return None


def expense_account( ledger : Ledger, expense_tax_class : ExpenseTaxClass ) -> Optional[ Account ]:
    """The first expense account with `expense_tax_class`, or None."""
    for account in ledger.accounts():
        if account.expense_tax_class == expense_tax_class:
            return account
        continue
    return None


def market_value( ledger : Ledger, holding : Account, *, through : Optional[ date ] = None ) -> Decimal:
    """A holding's market value: its cost (own natural balance) plus its valuation
    companion's accumulated appreciation, if any."""
    total = ledger.natural_balance( holding, through = through )
    valuation_account = valuation_of( ledger, holding )
    if valuation_account is not None:
        total += ledger.natural_balance( valuation_account, through = through )
    return total


def net_worth( ledger : Ledger, *, through : Optional[ date ] = None ) -> Decimal:
    """Total assets minus total liabilities (in natural terms) -- the partition's
    net worth as of `through`."""
    assets = sum(
        ( ledger.natural_balance( account, through = through )
          for account in ledger.accounts( account_type = AccountType.ASSET ) ),
        Decimal( '0' ),
    )
    liabilities = sum(
        ( ledger.natural_balance( account, through = through )
          for account in ledger.accounts( account_type = AccountType.LIABILITY ) ),
        Decimal( '0' ),
    )
    return assets - liabilities


def realize( ledger : Ledger,
             holding : Account,
             proceeds : Decimal,
             *,
             proceeds_account : Account,
             realized_gain_account : Account,
             on_date : date ) -> None:
    """Realize `proceeds` of `holding`'s market value into `proceeds_account`: draw
    down cost and valuation proportionally, recognize the realized gain (the
    valuation portion) into `realized_gain_account`, and reverse the Unrealized
    Gains equity. Net-worth-neutral -- the gain just moves from unrealized to
    realized (taxable). Caps at the holding's market value."""
    market = market_value( ledger, holding )
    if market <= 0:
        return
    proceeds = quantize_money( min( proceeds, market ) )
    valuation_account = valuation_of( ledger, holding )
    if valuation_account is None:
        cost_sold = proceeds
        gain = Decimal( '0' )
    else:
        fraction = proceeds / market
        cost_sold = quantize_money( ledger.natural_balance( holding ) * fraction )
        gain = proceeds - cost_sold
    postings = [ ( proceeds_account, -proceeds ), ( holding, cost_sold ) ]
    if gain != 0:
        unrealized_gain_account = system_account( ledger, SystemAccountRole.UNREALIZED_GAINS )
        if unrealized_gain_account is None:
            raise MissingAccountError( 'No Unrealized Gains equity account to realize against.' )
        postings += [
            ( valuation_account, gain ),
            ( unrealized_gain_account, -gain ),
            ( realized_gain_account, gain ),
        ]
    ledger.record( on_date, proceeds_account.currency, postings )
    return
