"""Stamp run-table display placements onto a materialized books, at capture.

A display convenience: it maps each account back to its input grouping and stamps an opaque
`AccountDisplayPlacement`, so the run table groups and orders columns as the inputs present them. Two
axes are stamped:

  - Expenses, by catalog `handle` -> `ExpenseClass` surface then `ExpenseCategory` section.
  - Income, by `IncomeTaxClass` -> a coarser income *source* (a meaningful rollup -- e.g. Investment
    Income totals interest, dividends and gains) then the owning *subject*. Because income accounts are
    keyed by (subject, tax class), pension and pre-tax retirement withdrawals share one `ORDINARY`
    account and so one source ("Pension & Withdrawals") -- named honestly for that engine-set granularity
    rather than split.

This is the one place carrying `parameter_sets`/grouping knowledge to the books; the accounts layer
stays oblivious, reading the placement opaquely. Best-effort by design: an account the mapping does not
cover keeps the engine-class fallback, and any failure leaves that pass unstamped. It must never fail
run capture -- hence the guard.
"""
from ucfp.accounts.books import AccountDisplayGroup, AccountDisplayPlacement, BooksOfAccount
from ucfp.accounts.enums import IncomeTaxClass
from ucfp.inputs.expenses import ordered_catalog
from ucfp.inputs.profile.schemas import Profile
from ucfp.parameter_sets.enums import ExpenseCategory, ExpenseClass


# Section order is enum declaration order (the catalog author's intent).
_CLASS_ORDER    = { klass : index for index, klass in enumerate( ExpenseClass ) }
_CATEGORY_ORDER = { category : index for index, category in enumerate( ExpenseCategory ) }

# Income sources: a coarser, user-facing grouping of income tax classes, in display order. Every income
# account carries a tax class, so the map covers them all -- an uncovered class would simply fall back to
# its own tax-class rung.
_INCOME_SOURCES = [
    ( 'earned', 'Earned Income', ( IncomeTaxClass.WAGES, ) ),
    ( 'pension-withdrawals', 'Pension & Withdrawals', ( IncomeTaxClass.ORDINARY, ) ),
    ( 'social-security', 'Social Security', ( IncomeTaxClass.SOCIAL_SECURITY, ) ),
    ( 'investment', 'Investment Income', ( IncomeTaxClass.TAXABLE_INTEREST,
                                           IncomeTaxClass.TAX_EXEMPT_INTEREST,
                                           IncomeTaxClass.QUALIFIED_DIVIDENDS,
                                           IncomeTaxClass.LONG_TERM_GAINS,
                                           IncomeTaxClass.SHORT_TERM_GAINS,
                                           IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
                                           IncomeTaxClass.SECOND_HOME_GAIN,
                                           IncomeTaxClass.SECTION_1250_GAIN,
                                           IncomeTaxClass.COLLECTIBLES_GAINS,
                                           IncomeTaxClass.TAX_FREE ) ),
    ( 'rental', 'Rental Income', ( IncomeTaxClass.GROSS_RENTAL, ) ),
]
_SOURCE_BY_CLASS = { tax_class : ( order, key, label )
                     for order, ( key, label, classes ) in enumerate( _INCOME_SOURCES )
                     for tax_class in classes }
# Within a subject, the tax-class accounts order by the tax class's own declaration order.
_TAX_CLASS_ORDER = { tax_class : index for index, tax_class in enumerate( IncomeTaxClass ) }


def stamp_display_placements( books : BooksOfAccount, profile : Profile ) -> None:
    """Stamp the books' accounts with their input grouping, best-effort. Each pass is guarded: a display
    concern must not be able to fail run capture, so a missing catalog or any error leaves that pass
    unstamped (the table then falls back to the engine-class grouping)."""
    for stamp in ( lambda : _stamp_expense_placements( books ),
                   lambda : _stamp_income_placements( books, profile ) ):
        try:
            stamp()
        except Exception:
            continue
        continue
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


def _stamp_income_placements( books : BooksOfAccount, profile : Profile ) -> None:
    subjects = { subject.handle : ( index, subject.name )
                 for index, subject in enumerate( profile.subjects ) }
    for account in books.accounts:
        if account.income_tax_class is None:
            continue
        source = _SOURCE_BY_CLASS.get( account.income_tax_class )
        if source is None:
            continue
        source_order, source_key, source_label = source
        path = [ AccountDisplayGroup( key = source_key, label = source_label, order = source_order ) ]
        subject = subjects.get( str( account.owner_handle ) ) if account.owner_handle is not None else None
        if subject is not None:
            subject_order, subject_name = subject
            path.append( AccountDisplayGroup( key   = 'subj-' + str( account.owner_handle ),
                                              label = subject_name, order = subject_order ) )
        account.display_placement = AccountDisplayPlacement(
            path = tuple( path ), order = _TAX_CLASS_ORDER[ account.income_tax_class ] )
        continue
    return
