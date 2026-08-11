"""The repository rejects duplicate account handles with an actionable error (#146).

Two accounts sharing a handle in one `BooksOfAccount` would otherwise trip the DB
`unique_account_handle_per_books` constraint and surface as an opaque `IntegrityError` 500 at the very end
of a run. The repository now guards it before persistence, raising a named `DuplicateAccountHandleError`
the forecast view renders inline. The collision only arose from stale/transition data, so these tests
force it directly.
"""
from django.test import TestCase

from organization.models import Organization
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass
from ucfp.accounts.exceptions import DuplicateAccountHandleError
from ucfp.accounts.repository import BooksOfAccountRepository


def _books_with_two_accounts_on( handle : str ) -> BooksOfAccount:
    """A books whose two asset holdings deliberately share `handle` -- the collision stale data produced
    (a DEPRECIATING vehicle and a COLLECTIBLES possession both minted onto `possession-1`)."""
    bookkeeper = Bookkeeper( BooksOfAccount( label = 'Dup' ) )
    bookkeeper.build_standard_chart()
    asset_root = bookkeeper.chart.root( AccountType.ASSET )
    civic = bookkeeper.create_holding( asset_root, '2009 Honda Civic', AssetClass.DEPRECIATING )
    coins = bookkeeper.create_holding( asset_root, 'Coins, cards, memorabilia', AssetClass.COLLECTIBLES )
    civic.handle = handle
    coins.handle = handle
    return bookkeeper.books


class DuplicateAccountHandleGuardTest( TestCase ):

    def test_save_rejects_a_duplicate_handle_naming_the_handle_and_accounts( self ):
        books        = _books_with_two_accounts_on( 'possession-1' )
        organization = Organization.objects.create( name = 'Dup Org' )
        with self.assertRaises( DuplicateAccountHandleError ) as caught:
            BooksOfAccountRepository().save( books, organization )
        message = str( caught.exception )
        self.assertIn( 'possession-1', message )                     # the colliding handle...
        self.assertIn( '2009 Honda Civic', message )                 # ...and both accounts, so it is actionable
        self.assertIn( 'Coins, cards, memorabilia', message )

    def test_the_error_is_a_valueerror_so_the_view_renders_it_inline( self ):
        # The forecast view surfaces run-time input errors via `except ValueError`; the guard rides it.
        self.assertTrue( issubclass( DuplicateAccountHandleError, ValueError ) )
