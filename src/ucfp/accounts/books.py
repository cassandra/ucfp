"""The double-entry domain aggregate -- pure Python, no Django.

`BooksOfAccount` is the data: a self-contained set of books (its `Account`s plus its
`Transaction`s/`Entry`s), the same thing whether it lives only in memory (a Forecast
projection) or is later persisted via the Repository. It carries no persistence concern --
no pk, no DB -- so it is keyed and compared by object identity (`eq=False`), which is what
in-memory building needs.

The behavior here is the structural invariants (account-tree placement, transaction
balance); the *mechanisms* that build and query the books live on the `Bookkeeper`, and
the `Chart`/`Ledger` views read them. See data/design/projection-model.md "Domain
vocabulary".
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SideType,
    SystemAccountRole,
)
from .exceptions import AccountStructureError, TransactionImbalanceError


@dataclass( eq = False )
class Account:
    """A node in a `BooksOfAccount`'s account tree.

    The tree is a forest of per-type roots: each root is parentless and carries an
    `account_type`; every other account inherits its type from its ancestry (see
    `effective_account_type`). Identity-compared (two accounts are equal only if the same
    object), so an account can serve as a dict key while the books are built in memory.
    """

    name              : str
    account_type      : Optional[ AccountType ]      = None
    parent            : Optional[ 'Account' ]        = None
    system_role       : Optional[ SystemAccountRole ] = None
    asset_class       : Optional[ AssetClass ]       = None
    is_valuation      : bool                         = False
    income_tax_class  : Optional[ IncomeTaxClass ]   = None
    expense_tax_class : Optional[ ExpenseTaxClass ]  = None
    description       : str                          = ''
    closed            : bool                         = False

    def __post_init__( self ):
        self._assert_valid_structure()
        return

    def __str__( self ):
        return self.name

    @property
    def is_root( self ) -> bool:
        return bool( self.parent is None )

    @property
    def is_system( self ) -> bool:
        return bool( ( self.parent is None ) or ( self.system_role is not None ) )

    @property
    def effective_account_type( self ) -> AccountType:
        """The account's type, walking to the type-bearing root if inherited."""
        if self.account_type is not None:
            return self.account_type
        return self.parent.effective_account_type

    @property
    def account_normal_type( self ) -> SideType:
        """The side (debit/credit) on which this account's balance is normal."""
        return self.effective_account_type.normal_side

    def _assert_valid_structure( self ):
        if self.is_root:
            if self.account_type is None:
                raise AccountStructureError( 'A root account must declare an account_type.' )
        else:
            if self.account_type is not None:
                raise AccountStructureError(
                    'A non-root account inherits its type and must not set account_type.'
                )
        if self.asset_class is not None:
            if self.is_root or self.effective_account_type != AccountType.ASSET:
                raise AccountStructureError(
                    'An asset_class may be set only on a non-root asset account.'
                )
        if self.income_tax_class is not None:
            if self.is_root or self.effective_account_type != AccountType.REVENUE:
                raise AccountStructureError(
                    'An income_tax_class may be set only on a non-root revenue account.'
                )
        if self.expense_tax_class is not None:
            if self.is_root or self.effective_account_type != AccountType.EXPENSE:
                raise AccountStructureError(
                    'An expense_tax_class may be set only on a non-root expense account.'
                )
        return


@dataclass( eq = False )
class Entry:
    """One side of a `Transaction`: a signed posting of an amount to an `Account`.

    Records a single positive `amount` in the books' single currency; `entry_direction`
    supplies the side. `signed_amount` combines the two (credit positive, debit negative)
    -- the form all arithmetic uses.
    """

    account         : Account
    amount          : Decimal
    entry_direction : SideType
    description     : str = ''

    @property
    def signed_amount( self ) -> Decimal:
        """The magnitude with its credit-positive sign."""
        if self.entry_direction == SideType.CREDIT:
            return self.amount
        return -self.amount


@dataclass( eq = False )
class Transaction:
    """A balanced movement of value: its date and its `Entry`s, whose signed amounts sum
    to zero (the core double-entry invariant). Its magnitude is derived, never stored."""

    transaction_date : date
    description      : str          = ''
    entries          : list[ Entry ] = field( default_factory = list )

    def __str__( self ):
        return f'{self.transaction_date} {self.description}'.strip()

    def balance( self ) -> Decimal:
        """Signed sum of the entries; zero when balanced."""
        return sum( ( entry.signed_amount for entry in self.entries ), Decimal( '0' ) )

    @property
    def is_balanced( self ) -> bool:
        return bool( self.balance() == Decimal( '0' ) )

    def assert_balanced( self ):
        if not self.is_balanced:
            raise TransactionImbalanceError(
                f'Transaction does not balance (residual {self.balance()}).'
            )
        return


@dataclass( eq = False )
class BooksOfAccount:
    """A self-contained set of books: its accounts and its transactions.

    The aggregate root and the unit of work -- built forward in memory by a `Bookkeeper`
    and, when wanted, persisted as a whole by the Repository. `label` names the books
    (e.g. a scenario's name); it owns no `Organization` reference, which is a persistence
    concern the Repository supplies.
    """

    label        : str                = ''
    accounts     : list[ Account ]     = field( default_factory = list )
    transactions : list[ Transaction ] = field( default_factory = list )
