"""Run-table placement: a plan Payment's expense account rolls up under Miscellaneous (#210 Phase 1).

A Payment materializes to a named LIVING expense account carrying a `payment:<label>` handle. That handle
has no catalog row, so without a routing rule it would fall to the engine-class (Living) fallback rather
than the Miscellaneous section a one-off payment belongs to. `_stamp_expense_placements` recognizes the
handle base and stamps the class -> category path directly; these tests pin that routing on a hand-built
books (the stamping is pure, so no forecast is needed).
"""
from django.test import TestCase

from ucfp.accounts.books import Account, BooksOfAccount
from ucfp.accounts.enums import AccountType, ExpenseTaxClass
from ucfp.inputs.profile.schemas import Profile
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.display_placement import _stamp_expense_placements


def _expense_books( *payment_handles ) -> BooksOfAccount:
    """A minimal books: an Expenses root and one payment expense account per handle."""
    root     = Account( name = 'Expenses', account_type = AccountType.EXPENSE )
    accounts = [ root ]
    for handle in payment_handles:
        accounts.append( Account(
            name = handle, parent = root, expense_tax_class = ExpenseTaxClass.LIVING, handle = handle ) )
    return BooksOfAccount( accounts = accounts )


def _path_keys( account ) -> list:
    return [ group.key for group in account.display_placement.path ]


class PaymentDisplayPlacementTests( TestCase ):
    """The stamping reads the expense catalog from the DB (to recognize catalog handles), so these seed
    the default parameter sets even though a payment account carries no catalog row."""

    def setUp( self ):
        seed_default_parameter_sets()

    def test_a_payment_account_lands_under_living_miscellaneous( self ):
        books = _expense_books( 'payment:college-tuition' )
        _stamp_expense_placements( books, Profile() )
        payment = books.accounts[ 1 ]
        self.assertEqual( _path_keys( payment ), [ 'class-living', 'cat-miscellaneous' ] )

    def test_distinct_payment_labels_share_the_rung_but_stay_separate_leaves( self ):
        # Two labels share the class -> Miscellaneous path (one rung) yet remain their own accounts.
        books = _expense_books( 'payment:college-tuition', 'payment:wedding' )
        _stamp_expense_placements( books, Profile() )
        tuition, wedding = books.accounts[ 1 ], books.accounts[ 2 ]
        self.assertEqual( _path_keys( tuition ), _path_keys( wedding ) )
        self.assertIsNot( tuition, wedding )

    def test_a_non_payment_expense_is_left_to_its_fallback( self ):
        # A handle-less expense account is not a payment, so this pass leaves it unstamped (the table
        # then groups it by its engine class).
        root  = Account( name = 'Expenses', account_type = AccountType.EXPENSE )
        plain = Account( name = 'Groceries', parent = root, expense_tax_class = ExpenseTaxClass.LIVING )
        books = BooksOfAccount( accounts = [ root, plain ] )
        _stamp_expense_placements( books, Profile() )
        self.assertIsNone( plain.display_placement )
