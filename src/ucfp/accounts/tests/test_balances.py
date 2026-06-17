"""Tests for balance computation, the transaction invariant, and the opening seed.

These cover the money arithmetic that is ground truth for the whole model, so
they are exercised even under the phase's otherwise-minimal testing policy.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from organization.models import Organization
from ucfp.accounts.enums import AccountType, CurrencyType, SideType
from ucfp.accounts.exceptions import (
    CurrencyConversionError,
    OpeningBalanceError,
    TransactionImbalanceError,
)
from ucfp.accounts.models import Account, Baseline
from ucfp.accounts.schemas import (
    CurrencyConversion,
    CurrencyConverter,
    OpeningBalances,
)

AS_OF = date( 2026, 6, 16 )


class CurrencyConverterTests(TestCase):
    """Pure conversion logic; no database."""

    def test_same_currency_is_identity(self):
        converter = CurrencyConverter()
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.USD,
            to_currency_type = CurrencyType.USD,
        )
        self.assertEqual( result, Decimal( '100' ) )

    def test_direct_conversion(self):
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '1.1' ) ), ),
        )
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.EUR,
            to_currency_type = CurrencyType.USD,
        )
        self.assertEqual( result, Decimal( '110.0' ) )

    def test_reverse_conversion_uses_inverse(self):
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '2' ) ), ),
        )
        result = converter.convert(
            amount = Decimal( '100' ),
            from_currency_type = CurrencyType.USD,
            to_currency_type = CurrencyType.EUR,
        )
        self.assertEqual( result, Decimal( '50' ) )

    def test_missing_conversion_raises(self):
        converter = CurrencyConverter()
        with self.assertRaises( CurrencyConversionError ):
            converter.convert(
                amount = Decimal( '100' ),
                from_currency_type = CurrencyType.EUR,
                to_currency_type = CurrencyType.USD,
            )

    def test_non_positive_rate_rejected(self):
        with self.assertRaises( ValueError ):
            CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '0' ) )

    def test_same_currency_must_have_unit_rate(self):
        with self.assertRaises( ValueError ):
            CurrencyConversion( CurrencyType.USD, CurrencyType.USD, Decimal( '2' ) )


class AccountsTestCase(TestCase):
    """Shared chart fixture: a USD organization with two leaf accounts."""

    def setUp(self):
        self.organization = Organization.objects.create( name = 'Acme' )
        Account.objects.initialize_chart( self.organization )
        self.assets_root = self._root( AccountType.ASSET )
        self.equity_root = self._root( AccountType.EQUITY )
        self.opening_balances = self.organization.accounts.get(
            system_role = 'opening_balances',
        )
        self.checking = Account.objects.create(
            organization = self.organization, parent = self.assets_root, name = 'Checking',
        )
        self.credit_card = Account.objects.create(
            organization = self.organization,
            parent = self._root( AccountType.LIABILITY ),
            name = 'Credit Card',
        )

    def _root(self, account_type):
        return self.organization.accounts.get(
            account_type = account_type, parent__isnull = True,
        )

    def _make_transaction(self, baseline):
        return baseline.transactions.create(
            transaction_date = AS_OF, description = '', currency = CurrencyType.USD,
        )


class EntryAmountTests(AccountsTestCase):

    def test_signed_amounts_and_derived_rate(self):
        baseline = Baseline.objects.create(
            organization = self.organization, as_of_date = AS_OF, label = 'B',
        )
        transaction = self._make_transaction( baseline )
        entry = transaction.entries.create(
            account = self.checking,
            amount = Decimal( '100' ),
            transaction_amount = Decimal( '110' ),
            entry_direction = SideType.DEBIT,
        )
        self.assertEqual( entry.signed_amount, Decimal( '-100' ) )
        self.assertEqual( entry.signed_transaction_amount, Decimal( '-110' ) )
        self.assertEqual( entry.conversion_rate, Decimal( '1.1' ) )


class AccountBalanceTests(AccountsTestCase):

    def test_signed_and_natural_balance(self):
        baseline = Baseline.objects.create(
            organization = self.organization, as_of_date = AS_OF, label = 'B',
        )
        transaction = self._make_transaction( baseline )
        transaction.entries.create(
            account = self.checking,
            amount = Decimal( '100' ),
            transaction_amount = Decimal( '100' ),
            entry_direction = SideType.DEBIT,
        )
        transaction.entries.create(
            account = self.equity_root,
            amount = Decimal( '100' ),
            transaction_amount = Decimal( '100' ),
            entry_direction = SideType.CREDIT,
        )
        # Asset (debit-normal): credit-positive signed balance is negative; the
        # natural balance flips it positive.
        self.assertEqual( self.checking.signed_balance( baseline ), Decimal( '-100' ) )
        self.assertEqual( self.checking.natural_balance( baseline ), Decimal( '100' ) )
        # Equity (credit-normal): signed and natural agree.
        self.assertEqual( self.equity_root.signed_balance( baseline ), Decimal( '100' ) )
        self.assertEqual( self.equity_root.natural_balance( baseline ), Decimal( '100' ) )


class TransactionBalanceTests(AccountsTestCase):

    def _two_sided(self, baseline, credit_amount):
        transaction = self._make_transaction( baseline )
        transaction.entries.create(
            account = self.checking,
            amount = Decimal( '100' ),
            transaction_amount = Decimal( '100' ),
            entry_direction = SideType.DEBIT,
        )
        transaction.entries.create(
            account = self.equity_root,
            amount = credit_amount,
            transaction_amount = credit_amount,
            entry_direction = SideType.CREDIT,
        )
        return transaction

    def test_balanced_transaction(self):
        baseline = Baseline.objects.create(
            organization = self.organization, as_of_date = AS_OF, label = 'B',
        )
        transaction = self._two_sided( baseline, Decimal( '100' ) )
        self.assertTrue( transaction.is_balanced )
        transaction.assert_balanced()

    def test_unbalanced_transaction_raises(self):
        baseline = Baseline.objects.create(
            organization = self.organization, as_of_date = AS_OF, label = 'B',
        )
        transaction = self._two_sided( baseline, Decimal( '60' ) )
        self.assertFalse( transaction.is_balanced )
        with self.assertRaises( TransactionImbalanceError ):
            transaction.assert_balanced()


class OpeningSeedTests(AccountsTestCase):

    def test_single_currency_seed_balances_and_plugs(self):
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '1000' ) )
        opening.add( self.credit_card, Decimal( '200' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        self.assertEqual( baseline.transactions.count(), 1 )
        transaction = baseline.transactions.get()
        self.assertTrue( transaction.is_balanced )
        # A = L + E by construction: 1000 = 200 + 800.
        self.assertEqual( self.checking.natural_balance( baseline ), Decimal( '1000' ) )
        self.assertEqual( self.credit_card.natural_balance( baseline ), Decimal( '200' ) )
        self.assertEqual( self.opening_balances.natural_balance( baseline ), Decimal( '800' ) )

    def test_discrepancy_surfaces_in_opening_balances(self):
        retained = Account.objects.create(
            organization = self.organization, parent = self.equity_root, name = 'Retained',
        )
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '1000' ) )
        opening.add( self.credit_card, Decimal( '200' ) )
        opening.add( retained, Decimal( '900' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        # Stated equity (900) overshoots the true residual (800) by 100, which
        # surfaces as a negative Opening Balances natural balance.
        self.assertEqual( self.opening_balances.natural_balance( baseline ), Decimal( '-100' ) )

    def test_multi_currency_seed_converts_and_balances(self):
        euro_savings = Account.objects.create(
            organization = self.organization,
            parent = self.assets_root,
            name = 'Euro Savings',
            currency = CurrencyType.EUR,
        )
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '1.1' ) ), ),
        )
        opening = OpeningBalances( converter = converter )
        opening.add( euro_savings, Decimal( '100' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        transaction = baseline.transactions.get()
        self.assertTrue( transaction.is_balanced )
        # The account balance stays in EUR; the plug lands in USD.
        self.assertEqual( euro_savings.natural_balance( baseline ), Decimal( '100' ) )
        self.assertEqual( self.opening_balances.natural_balance( baseline ), Decimal( '110' ) )
        euro_entry = transaction.entries.get( account = euro_savings )
        self.assertEqual( euro_entry.transaction_amount, Decimal( '110' ) )
        self.assertEqual( euro_entry.conversion_rate, Decimal( '1.1' ) )

    def test_missing_conversion_raises(self):
        euro_savings = Account.objects.create(
            organization = self.organization,
            parent = self.assets_root,
            name = 'Euro Savings',
            currency = CurrencyType.EUR,
        )
        opening = OpeningBalances()
        opening.add( euro_savings, Decimal( '100' ) )

        with self.assertRaises( CurrencyConversionError ):
            Baseline.objects.create_with_opening(
                organization = self.organization,
                as_of_date = AS_OF,
                label = 'Jun 2026',
                opening_balances = opening,
            )

    def test_converted_amount_is_rounded_half_up(self):
        euro_savings = Account.objects.create(
            organization = self.organization,
            parent = self.assets_root,
            name = 'Euro Savings',
            currency = CurrencyType.EUR,
        )
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '1.234565' ) ), ),
        )
        opening = OpeningBalances( converter = converter )
        opening.add( euro_savings, Decimal( '1' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        transaction = baseline.transactions.get()
        euro_entry = transaction.entries.get( account = euro_savings )
        # 1 * 1.234565 = 1.234565 -> half-up to 5 places -> 1.23457.
        self.assertEqual( euro_entry.transaction_amount, Decimal( '1.23457' ) )
        self.assertTrue( transaction.is_balanced )

    def test_sub_quantum_conversion_raises(self):
        euro_savings = Account.objects.create(
            organization = self.organization,
            parent = self.assets_root,
            name = 'Euro Savings',
            currency = CurrencyType.EUR,
        )
        converter = CurrencyConverter(
            ( CurrencyConversion( CurrencyType.EUR, CurrencyType.USD, Decimal( '0.1' ) ), ),
        )
        opening = OpeningBalances( converter = converter )
        # 0.00001 EUR * 0.1 = 0.000001 USD, which rounds to zero at the money scale.
        opening.add( euro_savings, Decimal( '0.00001' ) )

        with self.assertRaises( OpeningBalanceError ):
            Baseline.objects.create_with_opening(
                organization = self.organization,
                as_of_date = AS_OF,
                label = 'Jun 2026',
                opening_balances = opening,
            )

    def test_zero_starting_balance_is_skipped(self):
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '1000' ) )
        opening.add( self.credit_card, Decimal( '0' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        transaction = baseline.transactions.get()
        self.assertFalse( transaction.entries.filter( account = self.credit_card ).exists() )
        self.assertTrue( transaction.entries.filter( account = self.checking ).exists() )

    def test_plug_skipped_when_already_balanced(self):
        retained = Account.objects.create(
            organization = self.organization, parent = self.equity_root, name = 'Retained',
        )
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '1000' ) )   # asset, debit
        opening.add( retained, Decimal( '1000' ) )        # equity, credit -> nets to zero

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        transaction = baseline.transactions.get()
        self.assertFalse( transaction.entries.filter( account = self.opening_balances ).exists() )
        self.assertEqual( self.opening_balances.natural_balance( baseline ), Decimal( '0' ) )
        self.assertTrue( transaction.is_balanced )

    def test_negative_natural_balance_flips_side(self):
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '-200' ) )   # overdrawn asset

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        transaction = baseline.transactions.get()
        checking_entry = transaction.entries.get( account = self.checking )
        # A negative natural balance on a debit-normal account posts as a credit.
        self.assertEqual( checking_entry.entry_direction, SideType.CREDIT )
        self.assertEqual( self.checking.natural_balance( baseline ), Decimal( '-200' ) )
        self.assertTrue( transaction.is_balanced )

    def test_parent_account_balance_excludes_children(self):
        savings = Account.objects.create(
            organization = self.organization, parent = self.assets_root, name = 'Savings',
        )
        opening = OpeningBalances()
        opening.add( self.checking, Decimal( '1000' ) )
        opening.add( savings, Decimal( '500' ) )

        baseline = Baseline.objects.create_with_opening(
            organization = self.organization,
            as_of_date = AS_OF,
            label = 'Jun 2026',
            opening_balances = opening,
        )

        # Balance is per (account, baseline) with no subtree rollup: the assets
        # root has no entries of its own, so its balance is zero, not 1500.
        self.assertEqual( self.assets_root.natural_balance( baseline ), Decimal( '0' ) )
        self.assertEqual( self.checking.natural_balance( baseline ), Decimal( '1000' ) )
        self.assertEqual( savings.natural_balance( baseline ), Decimal( '500' ) )
