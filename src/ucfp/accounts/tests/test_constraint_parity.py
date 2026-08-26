"""DB-level enforcement of per-books account uniqueness (issue #223).

The `system_role` and `handle` uniqueness constraints are unconditional (no
`condition=`) so the database actually creates and enforces them on MySQL as well
as SQLite -- a partial "WHERE ... IS NOT NULL" index is silently dropped on MySQL.
These tests assert the DB contract directly (below the repository's app-level
handle guard): a duplicate non-null value is rejected, and NULLs stay exempt.
"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from organization.models import Organization
from ucfp.accounts.enums import AccountType, SystemAccountRole
from ucfp.accounts.models import AccountRecord, BooksOfAccountRecord


class AccountUniquenessConstraintTests( TestCase ):

    def setUp( self ):
        organization = Organization.objects.create( name = 'Constraint Test' )
        self.books = BooksOfAccountRecord.objects.create( organization = organization )

    def _account( self, name = 'A', **kwargs ) -> AccountRecord:
        return AccountRecord.objects.create( books = self.books, name = name, **kwargs )

    def test_duplicate_non_null_handle_rejected( self ):
        self._account( handle = 'cash' )
        with self.assertRaises( IntegrityError ):
            with transaction.atomic():
                self._account( handle = 'cash' )

    def test_multiple_null_handles_allowed( self ):
        self._account( handle = None )
        self._account( handle = None )          # does not raise -- NULLs are exempt
        self.assertEqual(
            AccountRecord.objects.filter( books = self.books, handle__isnull = True ).count(), 2 )

    def test_duplicate_non_null_system_role_rejected( self ):
        self._account( system_role = SystemAccountRole.OPENING_BALANCES )
        with self.assertRaises( IntegrityError ):
            with transaction.atomic():
                self._account( system_role = SystemAccountRole.OPENING_BALANCES )

    def test_multiple_null_system_roles_allowed( self ):
        self._account( system_role = None )
        self._account( system_role = None )     # does not raise -- NULLs are exempt
        self.assertEqual(
            AccountRecord.objects.filter( books = self.books, system_role__isnull = True ).count(), 2 )

    # --- root-per-type (GeneratedField key: account_type when parent IS NULL) ---
    def test_duplicate_root_account_type_rejected( self ):
        self._account( account_type = AccountType.ASSET )        # parent None -> a root
        with self.assertRaises( IntegrityError ):
            with transaction.atomic():
                self._account( account_type = AccountType.ASSET )

    def test_root_accounts_of_different_types_allowed( self ):
        self._account( account_type = AccountType.ASSET )
        self._account( account_type = AccountType.LIABILITY )    # different type -> allowed

    def test_non_root_accounts_of_same_type_allowed( self ):
        root = self._account( account_type = AccountType.ASSET )
        self._account( account_type = AccountType.ASSET, parent = root )
        self._account( account_type = AccountType.ASSET, parent = root )   # children -> key NULL -> exempt
        self.assertEqual(
            AccountRecord.objects.filter( books = self.books, parent = root ).count(), 2 )
