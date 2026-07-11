"""Stamp run-table display placements onto a materialized books, at capture.

A display convenience: it maps each catalog-derived expense account (by its catalog `handle`) back to
its input grouping -- its `ExpenseClass` surface and `ExpenseCategory` section -- and stamps a two-rung
`AccountDisplayPlacement`, so the run table groups and orders expenses as the inputs present them. This
is the one place that carries `parameter_sets` grouping knowledge to the books; the accounts layer stays
oblivious, reading the placement opaquely.

Best-effort by design: an account with no catalog handle (an engine tax/interest account) keeps the
engine-class fallback, and any failure leaves the books unstamped (so the table falls back to today's
grouping). It must never fail run capture -- hence the guard.
"""
from ucfp.accounts.books import AccountDisplayGroup, AccountDisplayPlacement, BooksOfAccount
from ucfp.inputs.expenses import ordered_catalog
from ucfp.parameter_sets.enums import ExpenseCategory, ExpenseClass


# Section order is enum declaration order (the catalog author's intent); a large gap below the
# engine-class fallback order so stamped groups always sort ahead of it.
_CLASS_ORDER    = { klass : index for index, klass in enumerate( ExpenseClass ) }
_CATEGORY_ORDER = { category : index for index, category in enumerate( ExpenseCategory ) }


def stamp_expense_placements( books : BooksOfAccount ) -> None:
    """Stamp expense accounts with their input grouping, best-effort. Never raises: a display concern
    must not be able to fail run capture, so a missing catalog or any error leaves the books unstamped
    (the table then falls back to the engine-class grouping)."""
    try:
        _stamp_expense_placements( books )
    except Exception:
        return


def _stamp_expense_placements( books : BooksOfAccount ) -> None:
    catalog = { row.handle : row for row in ordered_catalog() }
    for account in books.accounts:
        if account.handle is None:
            continue
        row = catalog.get( str( account.handle ) )
        if row is None:
            continue
        account.display_placement = AccountDisplayPlacement(
            path = ( AccountDisplayGroup( key   = 'class-' + row.expense_class.name.lower(),
                                          label = row.expense_class.label,
                                          order = _CLASS_ORDER[ row.expense_class ] ),
                     AccountDisplayGroup( key   = 'cat-' + row.category.name.lower(),
                                          label = row.category.label,
                                          order = _CATEGORY_ORDER[ row.category ] ) ),
            order = row.order )
        continue
    return
