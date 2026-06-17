from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models, transaction

from .constants import DEFAULT_ROOT_ACCOUNT_NAMES, OPENING_TRANSACTION_DESCRIPTION
from .enums import AccountType, SideType, SystemAccountRole
from .exceptions import OpeningBalanceError
from .money_utils import quantize_money

if TYPE_CHECKING:
    # Imported only for type annotations; a runtime import would create a
    # managers <-> models cycle (models imports these managers).
    from datetime import date

    from organization.models import Organization

    from .enums import AssetClass, CurrencyType
    from .models import Account, Journal, Transaction
    from .schemas import CurrencyConverter, OpeningBalances, StartingBalance


class AccountManager( models.Manager ):

    @transaction.atomic
    def initialize_chart( self, organization : 'Organization' ) -> None:
        """Create the standard chart of accounts for `organization` if absent.

        Builds one root account per AccountType (parentless and type-bearing) and
        an Opening Balances equity account beneath the Equity root. Idempotent: a
        second call makes no changes, so it is safe to call on demand whenever a
        chart is needed.
        """
        roots = dict()
        for account_type in AccountType.all():
            root, _created = self.get_or_create(
                organization = organization,
                parent = None,
                account_type = account_type,
                defaults = {
                    'name': DEFAULT_ROOT_ACCOUNT_NAMES[ account_type ],
                },
            )
            roots[ account_type ] = root
            continue
        for system_role in ( SystemAccountRole.OPENING_BALANCES, SystemAccountRole.UNREALIZED_GAINS ):
            self.get_or_create(
                organization = organization,
                system_role = system_role,
                defaults = {
                    'parent': roots[ AccountType.EQUITY ],
                    'name': system_role.label,
                },
            )
            continue
        return

    @transaction.atomic
    def create_holding( self,
                        organization : 'Organization',
                        parent       : 'Account',
                        name         : str,
                        asset_class  : 'AssetClass',
                        currency     : 'CurrencyType' = None ) -> 'Account':
        """Create an asset holding and, for classes that accrue unrealized gains,
        its companion valuation child. Market value = holding cost + valuation; the
        holding itself carries the cost basis."""
        fields = {
            'organization': organization,
            'parent': parent,
            'name': name,
            'asset_class': asset_class,
        }
        if currency is not None:
            fields[ 'currency' ] = currency
        holding = self.create( **fields )
        if asset_class.accrues_unrealized_gains:
            self.create(
                organization = organization,
                parent = holding,
                name = f'{name} (Valuation)',
                currency = holding.currency,
                is_valuation = True,
            )
        return holding


class JournalManager( models.Manager ):

    @transaction.atomic
    def create_with_opening( self,
                             organization     : 'Organization',
                             as_of_date       : 'date',
                             label            : str,
                             opening_balances : 'OpeningBalances',
                             description      : str = OPENING_TRANSACTION_DESCRIPTION ) -> 'Journal':
        """Create a journal and seed its opening financial state.

        Builds one balanced opening transaction. Each StartingBalance is posted on
        the side that makes its account's natural balance equal the given amount,
        recorded in both the account currency and the transaction currency (via the
        OpeningBalances converter); a single Opening Balances entry absorbs the
        residual, so Assets = Liabilities + Equity holds by construction and any
        reconciliation gap lands visibly in Opening Balances.

        The opening transaction's currency is the Opening Balances equity account's
        currency. Requires the organization's chart to be initialized (see
        AccountManager.initialize_chart). Raises CurrencyConversionError if an
        account's currency differs from the transaction currency and the converter
        lacks the needed conversion.
        """
        opening_balances_account = organization.accounts.get(
            system_role = SystemAccountRole.OPENING_BALANCES,
        )
        transaction_currency = opening_balances_account.currency
        journal = self.create(
            organization = organization,
            as_of_date = as_of_date,
            label = label,
        )
        opening_transaction = journal.transactions.create(
            transaction_date = as_of_date,
            description = description,
            currency = transaction_currency,
        )
        for starting_balance in opening_balances.starting_balances:
            self._add_starting_entry(
                opening_transaction = opening_transaction,
                starting_balance = starting_balance,
                transaction_currency = transaction_currency,
                converter = opening_balances.converter,
            )
            continue
        self._add_opening_balances_plug(
            opening_transaction = opening_transaction,
            opening_balances_account = opening_balances_account,
        )
        opening_transaction.assert_balanced()
        return journal

    def _add_starting_entry( self,
                             opening_transaction  : 'Transaction',
                             starting_balance     : 'StartingBalance',
                             transaction_currency : 'CurrencyType',
                             converter            : 'CurrencyConverter' ) -> None:
        account = starting_balance.account
        natural_amount = starting_balance.amount
        if natural_amount == 0:
            return
        transaction_natural_amount = quantize_money(
            converter.convert(
                amount = natural_amount,
                from_currency_type = account.currency,
                to_currency_type = transaction_currency,
            )
        )
        if transaction_natural_amount == 0:
            raise OpeningBalanceError(
                f'Starting balance for "{account}" rounds to zero in the '
                f'transaction currency ({transaction_currency}); its amount or '
                f'conversion rate is too small to record.'
            )
        if account.account_normal_type == SideType.CREDIT:
            signed_amount = natural_amount
            signed_transaction_amount = transaction_natural_amount
        else:
            signed_amount = -natural_amount
            signed_transaction_amount = -transaction_natural_amount
        self._create_entry(
            opening_transaction = opening_transaction,
            account = account,
            signed_amount = signed_amount,
            signed_transaction_amount = signed_transaction_amount,
        )
        return

    def _add_opening_balances_plug( self,
                                    opening_transaction      : 'Transaction',
                                    opening_balances_account : 'Account' ) -> None:
        # The Opening Balances account is in the transaction currency, so its
        # account-currency and transaction-currency magnitudes are identical.
        plug_signed_amount = -opening_transaction.balance()
        if plug_signed_amount == 0:
            return
        self._create_entry(
            opening_transaction = opening_transaction,
            account = opening_balances_account,
            signed_amount = plug_signed_amount,
            signed_transaction_amount = plug_signed_amount,
        )
        return

    def _create_entry( self,
                       opening_transaction       : 'Transaction',
                       account                   : 'Account',
                       signed_amount             : Decimal,
                       signed_transaction_amount : Decimal ) -> None:
        if signed_amount > 0:
            entry_direction = SideType.CREDIT
        else:
            entry_direction = SideType.DEBIT
        opening_transaction.entries.create(
            account = account,
            amount = abs( signed_amount ),
            transaction_amount = abs( signed_transaction_amount ),
            entry_direction = entry_direction,
        )
        return
