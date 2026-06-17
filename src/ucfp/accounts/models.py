import uuid
from decimal import Decimal

from django.db import models

from common.labeled_enum import LabeledEnumField, NullableLabeledEnumField
from common.models import BoundedDecimalField, TimestampedModel

from organization.models import Organization

from .constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from .enums import AccountType, AssetClass, CurrencyType, SideType, SystemAccountRole
from .exceptions import (
    AccountStructureError,
    EntryImmutableError,
    SystemAccountError,
    TransactionImbalanceError,
)
from .managers import AccountManager, JournalManager


class Journal( TimestampedModel ):
    """A persisted, dated starting financial state, and the partition that owns
    transactions.

    Many journals may coexist per organization (e.g. "Oct 2026 planning",
    "Feb 2027 revision"); each is its own partition, so transactions in different
    journals never double-count. Accounts are shared across journals (one chart
    per organization) -- only transactions are partitioned by journal.
    """

    objects = JournalManager()

    organization = models.ForeignKey(
        Organization,
        verbose_name = 'Organization',
        related_name = 'journals',
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
    as_of_date = models.DateField(
        'As Of Date',
        null = False,
    )
    label = models.CharField(
        'Label',
        max_length = 128,
        null = False,
        blank = False,
    )

    class Meta:
        verbose_name = 'Journal'
        verbose_name_plural = 'Journals'

    def __str__(self):
        return f'{self.label} ({self.as_of_date})'


class Account( TimestampedModel ):
    """A node in an organization's shared chart of accounts.

    The chart is a forest of per-type roots: each AccountType has exactly one
    parentless root that carries the type, and every other account inherits its
    type from its ancestry (see effective_account_type). Accounts are shared
    across journals; an account has no single global balance -- balance is
    computed per (account, journal).

    System accounts -- the per-type roots and the well-known role accounts (see
    SystemAccountRole) -- are created by `objects.initialize_chart` and are
    protected from deletion and closing.
    """

    objects = AccountManager()

    organization = models.ForeignKey(
        Organization,
        verbose_name = 'Organization',
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
    name = models.CharField(
        'Name',
        max_length = 128,
        null = False,
        blank = False,
    )
    description = models.TextField(
        'Description',
        blank = True,
        default = '',
    )
    currency = LabeledEnumField(
        CurrencyType,
        verbose_name = 'Currency',
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
                fields = [ 'organization', 'account_type' ],
                condition = models.Q( parent__isnull = True ),
                name = 'unique_root_account_per_type',
            ),
            models.UniqueConstraint(
                fields = [ 'organization', 'system_role' ],
                condition = models.Q( system_role__isnull = False ),
                name = 'unique_system_account_role_per_organization',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_root(self) -> bool:
        return bool( self.parent_id is None )

    @property
    def is_system(self) -> bool:
        return bool( ( self.parent_id is None ) or ( self.system_role is not None ) )

    @property
    def effective_account_type(self) -> AccountType:
        """The account's type, walking to the type-bearing root if inherited."""
        if self.account_type is not None:
            return self.account_type
        return self.parent.effective_account_type

    @property
    def account_normal_type(self) -> SideType:
        """The side (debit/credit) on which this account's balance is normal."""
        return self.effective_account_type.normal_side

    def signed_balance( self, journal : 'Journal' ) -> Decimal:
        """Credit-positive balance within `journal`, in the account's currency.

        The plain sum of this account's own entries' signed_amount (no currency
        conversion: every entry on an account is in that account's currency).
        Descendants are not rolled up -- balance is per (account, journal).
        """
        totals = self.entries.filter( transaction__journal = journal ).aggregate(
            credit_total = models.Sum(
                'amount',
                filter = models.Q( entry_direction = SideType.CREDIT ),
            ),
            debit_total = models.Sum(
                'amount',
                filter = models.Q( entry_direction = SideType.DEBIT ),
            ),
        )
        credit_total = totals[ 'credit_total' ] or Decimal( '0' )
        debit_total = totals[ 'debit_total' ] or Decimal( '0' )
        return credit_total - debit_total

    def natural_balance( self, journal : 'Journal' ) -> Decimal:
        """Display balance: positive in the account type's normal direction."""
        signed = self.signed_balance( journal )
        if self.account_normal_type == SideType.DEBIT:
            return -signed
        return signed

    def close(self):
        """Archive this account from the chart (non-destructive)."""
        self.closed = True
        self.save()
        return

    def save( self, *args, **kwargs ):
        self._assert_valid_structure()
        self._assert_not_closing_system_account()
        return super().save( *args, **kwargs )

    def delete( self, *args, **kwargs ):
        if self.is_system:
            raise SystemAccountError( 'A system account cannot be deleted.' )
        return super().delete( *args, **kwargs )

    def _assert_valid_structure( self ):
        if self.is_root:
            if self.account_type is None:
                raise AccountStructureError(
                    'A root account must declare an account_type.'
                )
        else:
            if self.account_type is not None:
                raise AccountStructureError(
                    'A non-root account inherits its type and must not set account_type.'
                )
            if self.parent.organization_id != self.organization_id:
                raise AccountStructureError(
                    'A child account must belong to the same organization as its parent.'
                )
            self._assert_no_parent_cycle()
        if self.asset_class is not None:
            if self.is_root or self.effective_account_type != AccountType.ASSET:
                raise AccountStructureError(
                    'An asset_class may be set only on a non-root asset account.'
                )
        return

    def _assert_no_parent_cycle( self ):
        # A new (unsaved) account cannot yet be an ancestor of anything, so only
        # re-parenting an existing account can introduce a cycle. Walking to the
        # root also bounds the otherwise-unbounded recursion in
        # effective_account_type.
        if self.pk is None:
            return
        ancestor = self.parent
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise AccountStructureError( 'An account cannot be its own ancestor.' )
            ancestor = ancestor.parent
            continue
        return

    def _assert_not_closing_system_account( self ):
        if self.closed and self.is_system:
            raise SystemAccountError( 'A system account cannot be closed.' )
        return


class Transaction( TimestampedModel ):
    """A balanced movement of value within a single Journal partition.

    Comprises at least one debit and one credit Entry whose signed amounts sum to
    zero in `currency` (after per-entry conversion) -- the core double-entry
    invariant. Its magnitude (the common "amount") is derived from its entries
    and never stored.
    """

    journal = models.ForeignKey(
        Journal,
        verbose_name = 'Journal',
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
    currency = LabeledEnumField(
        CurrencyType,
        verbose_name = 'Currency',
    )

    class Meta:
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def __str__(self):
        return f'{self.transaction_date} {self.description}'.strip()

    def balance( self ) -> Decimal:
        """Signed sum of the entries in the transaction currency; zero when balanced."""
        total = Decimal( '0' )
        for entry in self.entries.all():
            total += entry.signed_transaction_amount
            continue
        return total

    @property
    def is_balanced( self ) -> bool:
        return bool( self.balance() == Decimal( '0' ) )

    def assert_balanced( self ):
        if not self.is_balanced:
            raise TransactionImbalanceError(
                f'Transaction {self.uuid} does not balance (residual {self.balance()}).'
            )
        return


class Entry( TimestampedModel ):
    """One side of a Transaction: a signed posting of an amount to an Account.

    An entry is immutable once created -- it carries no edit path and no status
    lifecycle (pending/posted/discarded). It records its magnitude in two
    currencies: `amount` in the account's currency and `transaction_amount` in the
    transaction's currency (equal when the two currencies match). `entry_direction`
    supplies the side; `signed_amount` and `signed_transaction_amount` combine
    magnitude and side (credit positive, debit negative). The conversion rate is
    derived from the two amounts (see `conversion_rate`), not stored.
    """

    account = models.ForeignKey(
        Account,
        verbose_name = 'Account',
        related_name = 'entries',
        on_delete = models.PROTECT,
        null = False,
        blank = False,
    )
    transaction = models.ForeignKey(
        Transaction,
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
    transaction_amount = BoundedDecimalField(
        'Transaction Amount',
        max_digits = MONEY_MAX_DIGITS,
        decimal_places = MONEY_DECIMAL_PLACES,
        min_value = Decimal( '0' ),
        exclusive_min = True,
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
            models.CheckConstraint(
                condition = models.Q( transaction_amount__gt = 0 ),
                name = 'entry_transaction_amount_strictly_positive',
            ),
        ]

    def __str__(self):
        return f'{self.entry_direction.label} {self.amount} {self.account}'

    @property
    def signed_amount(self) -> Decimal:
        """The magnitude with its credit-positive sign, in the account's currency."""
        if self.entry_direction == SideType.CREDIT:
            return self.amount
        return -self.amount

    @property
    def signed_transaction_amount(self) -> Decimal:
        """The magnitude with its credit-positive sign, in the transaction currency."""
        if self.entry_direction == SideType.CREDIT:
            return self.transaction_amount
        return -self.transaction_amount

    @property
    def conversion_rate(self) -> Decimal:
        """Derived account-to-transaction rate (transaction_amount / amount)."""
        return self.transaction_amount / self.amount

    def save( self, *args, **kwargs ):
        if self.pk is not None:
            raise EntryImmutableError( 'An Entry is immutable once created.' )
        return super().save( *args, **kwargs )
