"""Persistence schema for the double-entry domain.

These `*Record` models are the *persisted* form of the `BooksOfAccount` domain (see
`books.py`) -- dumb tables, no behavior. The data, invariants, and mechanisms live in the
pure-Python domain (`books.py`, `bookkeeper.py`); the `BooksOfAccountRepository` maps
between the two. So there is no balance arithmetic, no structural validation, and no
chart-building managers here -- only columns and the integrity constraints worth enforcing
at the database.

A `BooksOfAccountRecord` is the aggregate root: it owns its `AccountRecord`s and
`TransactionRecord`s (which own `EntryRecord`s). Accounts are scoped to one books, never
shared -- the `Organization` owns books, not accounts.
"""
import uuid
from decimal import Decimal

from django.db import models

from common.labeled_enum import LabeledEnumField, NullableLabeledEnumField
from common.models import BoundedDecimalField, TimestampedModel

from organization.models import Organization

from .constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from .enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SideType,
    SystemAccountRole,
)


class BooksOfAccountRecord( TimestampedModel ):
    """A persisted set of books: the aggregate root owning its accounts and transactions.
    The `Organization` (the tenant) owns these; each is self-contained."""

    organization = models.ForeignKey(
        Organization,
        verbose_name = 'Organization',
        related_name = 'books',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    label = models.CharField(
        'Label',
        max_length = 128,
        null = False,
        blank = True,
        default = '',
    )

    class Meta:
        verbose_name = 'Books of Account'
        verbose_name_plural = 'Books of Account'

    def __str__( self ):
        return self.label or f'Books {self.uuid}'


class AccountRecord( TimestampedModel ):
    """A persisted account node. Type placement and tree validity are domain concerns;
    this carries only the columns and the per-books uniqueness of roots and system roles."""

    books = models.ForeignKey(
        BooksOfAccountRecord,
        verbose_name = 'Books',
        related_name = 'accounts',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    parent = models.ForeignKey(
        'self',
        verbose_name = 'Parent',
        related_name = 'children',
        on_delete = models.CASCADE,
        null = True,
        blank = True,
    )
    account_type = NullableLabeledEnumField(
        AccountType,
        verbose_name = 'Account Type',
        default = None,
    )
    system_role = NullableLabeledEnumField(
        SystemAccountRole,
        verbose_name = 'System Role',
        default = None,
    )
    asset_class = NullableLabeledEnumField(
        AssetClass,
        verbose_name = 'Asset Class',
        default = None,
    )
    is_valuation = models.BooleanField(
        'Is Valuation',
        default = False,
    )
    income_tax_class = NullableLabeledEnumField(
        IncomeTaxClass,
        verbose_name = 'Income Tax Class',
        default = None,
    )
    expense_tax_class = NullableLabeledEnumField(
        ExpenseTaxClass,
        verbose_name = 'Expense Tax Class',
        default = None,
    )
    name = models.CharField(
        'Name',
        max_length = 128,
        null = False,
        blank = False,
    )
    handle = models.CharField(
        'Handle',
        max_length = 128,
        null = True,
        blank = True,
        default = None,
    )
    owner_handle = models.CharField(
        'Owner Handle',
        max_length = 128,
        null = True,
        blank = True,
        default = None,
    )
    description = models.TextField(
        'Description',
        blank = True,
        default = '',
    )
    closed = models.BooleanField(
        'Closed',
        default = False,
    )

    class Meta:
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'
        constraints = [
            models.UniqueConstraint(
                fields = [ 'books', 'account_type' ],
                condition = models.Q( parent__isnull = True ),
                name = 'unique_root_account_per_type',
            ),
            models.UniqueConstraint(
                fields = [ 'books', 'system_role' ],
                condition = models.Q( system_role__isnull = False ),
                name = 'unique_system_account_role_per_books',
            ),
            models.UniqueConstraint(
                fields = [ 'books', 'handle' ],
                condition = models.Q( handle__isnull = False ),
                name = 'unique_account_handle_per_books',
            ),
        ]

    def __str__( self ):
        return self.name


class TransactionRecord( TimestampedModel ):
    """A persisted transaction within a books. Balance is a domain invariant, not stored
    or enforced here."""

    books = models.ForeignKey(
        BooksOfAccountRecord,
        verbose_name = 'Books',
        related_name = 'transactions',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    transaction_date = models.DateField(
        'Transaction Date',
        null = False,
    )
    description = models.TextField(
        'Description',
        blank = True,
        default = '',
    )

    class Meta:
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def __str__( self ):
        return f'{self.transaction_date} {self.description}'.strip()


class EntryRecord( TimestampedModel ):
    """A persisted entry: a signed posting of an amount to an account. The amount is a
    positive magnitude in the books' single currency; `entry_direction` gives the side."""

    account = models.ForeignKey(
        AccountRecord,
        verbose_name = 'Account',
        related_name = 'entries',
        on_delete = models.PROTECT,
        null = False,
        blank = False,
    )
    transaction = models.ForeignKey(
        TransactionRecord,
        verbose_name = 'Transaction',
        related_name = 'entries',
        on_delete = models.CASCADE,
        null = False,
        blank = False,
    )
    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    amount = BoundedDecimalField(
        'Amount',
        max_digits = MONEY_MAX_DIGITS,
        decimal_places = MONEY_DECIMAL_PLACES,
        min_value = Decimal( '0' ),
        exclusive_min = True,
    )
    entry_direction = LabeledEnumField(
        SideType,
        verbose_name = 'Entry Direction',
    )
    description = models.TextField(
        'Description',
        blank = True,
        default = '',
    )

    class Meta:
        verbose_name = 'Entry'
        verbose_name_plural = 'Entries'
        constraints = [
            models.CheckConstraint(
                condition = models.Q( amount__gt = 0 ),
                name = 'entry_amount_strictly_positive',
            ),
        ]

    def __str__( self ):
        return f'{self.entry_direction.label} {self.amount} {self.account}'
