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


def _books_with_holdings( *specs ) -> BooksOfAccount:
    """A books with one asset holding per `(name, handle)` spec (handle may be None). The class is
    irrelevant -- the handle-uniqueness guard groups by handle regardless -- so every holding is a
    COLLECTIBLES one."""
    bookkeeper = Bookkeeper( BooksOfAccount( label = 'Dup' ) )
    bookkeeper.build_standard_chart()
    asset_root = bookkeeper.chart.root( AccountType.ASSET )
    for name, handle in specs:
        holding = bookkeeper.create_holding( asset_root, name, AssetClass.COLLECTIBLES )
        holding.handle = handle
    return bookkeeper.books


class DuplicateAccountHandleGuardTest( TestCase ):

    def test_save_rejects_a_duplicate_handle_naming_the_handle_and_accounts( self ):
        # The stale-data collision: two holdings both minted onto possession-1.
        books = _books_with_holdings(
            ( '2009 Honda Civic', 'possession-1' ), ( 'Coins, cards, memorabilia', 'possession-1' ) )
        organization = Organization.objects.create( name = 'Dup Org' )
        with self.assertRaises( DuplicateAccountHandleError ) as caught:
            BooksOfAccountRepository().save( books, organization )
        message = str( caught.exception )
        self.assertIn( 'possession-1', message )                     # the colliding handle...
        self.assertIn( '2009 Honda Civic', message )                 # ...and both accounts, so it is actionable
        self.assertIn( 'Coins, cards, memorabilia', message )

    def test_save_names_every_colliding_handle_group( self ):
        # Two separate collisions in one books -- exercises the "; " join the single-collision case skips.
        books = _books_with_holdings(
            ( 'Civic', 'possession-1' ), ( 'Coins', 'possession-1' ),
            ( 'Bullion', 'possession-2' ), ( 'Cards', 'possession-2' ) )
        organization = Organization.objects.create( name = 'Multi Org' )
        with self.assertRaises( DuplicateAccountHandleError ) as caught:
            BooksOfAccountRepository().save( books, organization )
        message = str( caught.exception )
        self.assertIn( 'possession-1', message )
        self.assertIn( 'possession-2', message )

    def test_save_allows_multiple_null_handle_accounts( self ):
        # Null handles are exempt from the DB's unique constraint (condition: handle IS NOT NULL), so two
        # handleless holdings persist fine -- the guard must not false-positive on them.
        books = _books_with_holdings(
            ( 'Cash', None ), ( 'Wallet', None ), ( 'Ring', 'possession-1' ) )
        organization = Organization.objects.create( name = 'Nulls Org' )
        self.assertIsNotNone( BooksOfAccountRepository().save( books, organization ) )

    def test_the_error_is_a_valueerror_so_the_view_renders_it_inline( self ):
        # The forecast view surfaces run-time input errors via `except ValueError`; the guard rides it.
        self.assertTrue( issubclass( DuplicateAccountHandleError, ValueError ) )
