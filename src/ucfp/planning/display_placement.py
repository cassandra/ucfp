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
  - Assets, by `AssetClass` -> the input *pane* the assets step groups them under (Financial Accounts /
    Properties / Possessions) then the asset class, with holdings ordered by their profile position.

This is the one place carrying `parameter_sets`/grouping knowledge to the books; the accounts layer
stays oblivious, reading the placement opaquely. Best-effort by design: an account the mapping does not
cover keeps the engine-class fallback, and any failure leaves that pass unstamped. It must never fail
run capture -- hence the guard.
"""
import logging
from dataclasses import dataclass

from ucfp.accounts.books import AccountDisplayGroup, AccountDisplayPlacement, BooksOfAccount
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.inputs.expenses import ordered_catalog
from ucfp.inputs.profile.schemas import Profile
from ucfp.parameter_sets.enums import ExpenseCategory, ExpenseClass


logger = logging.getLogger( __name__ )


# The order a leaf whose input position is unknown sorts to -- after every input-ordered sibling. Mirrors
# `_FALLBACK_ORDER` in accounts/books_table.py (the engine-class fallback rung order); the two live a
# layer apart but must stay in lockstep so a stamped leaf always sorts ahead of a fallback one.
_UNMAPPED_ORDER = 10 ** 6

# Section order is enum declaration order (the catalog author's intent).
_CLASS_ORDER    = { klass : index for index, klass in enumerate( ExpenseClass ) }
_CATEGORY_ORDER = { category : index for index, category in enumerate( ExpenseCategory ) }

# The Vehicle pane generates the car purchase and its financing payments outside the expense catalog
# (materialization mints these stable handles for their accounts). They belong in the same Vehicle
# section as the catalog running costs, leading them (ordered ahead of insurance at 10) -- the
# acquisition before the operating costs.
CAR_PURCHASE_HANDLE = 'car-purchase'
CAR_PAYMENTS_HANDLE = 'car-payments'
_GENERATED_VEHICLE_ORDER = { CAR_PURCHASE_HANDLE : 0, CAR_PAYMENTS_HANDLE : 5 }

# A property expense's account handle scopes the catalog handle to its property (`property-tax:rental-1`),
# so each property's costs are a distinct account -- a unique handle, keeping its own per-property tax
# class -- that still groups by the base catalog handle (the part before the separator).
_PROPERTY_EXPENSE_HANDLE_SEP = ':'


def property_expense_handle( expense_handle : str, property_handle : str ) -> str:
    """The account handle for `expense_handle` scoped to `property_handle` -- unique per property, yet
    grouping by its base catalog handle. Minted in materialization, parsed back here for placement."""
    return f'{expense_handle}{_PROPERTY_EXPENSE_HANDLE_SEP}{property_handle}'


def _base_expense_handle( account_handle : str ) -> str:
    """The catalog handle an account groups under: a property-scoped handle's part before the separator,
    or the whole handle when it carries none (a catalog or generated expense)."""
    return account_handle.split( _PROPERTY_EXPENSE_HANDLE_SEP, 1 )[ 0 ]


@dataclass( frozen = True )
class _Grouping:
    """A coarse display group -- its opaque column `key`, display `label`, and the fine classes that roll
    up into it. The tables below list them in display order; a class's position in its group's table is
    its group's order."""

    key     : str
    label   : str
    classes : tuple


# Asset panes: the coarse grouping the assets input step presents, one super-rung above the asset class,
# derived from the class. In declaration display order; classes not named here are the financial accounts.
_ASSET_PANES = [
    _Grouping( 'financial', 'Financial Accounts',
               ( AssetClass.CASH, AssetClass.STOCKS, AssetClass.DIVIDEND_STOCKS, AssetClass.BONDS,
                 AssetClass.CDS, AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ) ),
    _Grouping( 'properties', 'Properties',
               ( AssetClass.REAL_ESTATE_RESIDENCE, AssetClass.REAL_ESTATE_SECOND_HOME,
                 AssetClass.REAL_ESTATE_RENTAL ) ),
    _Grouping( 'possessions', 'Possessions',
               ( AssetClass.PRECIOUS_METALS, AssetClass.COLLECTIBLES, AssetClass.DEPRECIATING ) ),
]
_PANE_BY_CLASS = { asset_class : ( order, pane )
                   for order, pane in enumerate( _ASSET_PANES )
                   for asset_class in pane.classes }
# Within a pane, the classes order by their own declaration order.
_ASSET_CLASS_ORDER = { asset_class : index for index, asset_class in enumerate( AssetClass ) }

# Income sources: a coarser, user-facing grouping of income tax classes, in display order. Every income
# account carries a tax class, so the map covers them all -- an uncovered class would simply fall back to
# its own tax-class rung.
_INCOME_SOURCES = [
    _Grouping( 'earned', 'Earned Income', ( IncomeTaxClass.WAGES, ) ),
    _Grouping( 'pension-withdrawals', 'Pension & Withdrawals',
               ( IncomeTaxClass.ORDINARY, IncomeTaxClass.RETIREMENT_DISTRIBUTION ) ),
    _Grouping( 'social-security', 'Social Security', ( IncomeTaxClass.SOCIAL_SECURITY, ) ),
    _Grouping( 'investment', 'Investment Income',
               ( IncomeTaxClass.TAXABLE_INTEREST, IncomeTaxClass.TAX_EXEMPT_INTEREST,
                 IncomeTaxClass.QUALIFIED_DIVIDENDS, IncomeTaxClass.LONG_TERM_GAINS,
                 IncomeTaxClass.SHORT_TERM_GAINS, IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
                 IncomeTaxClass.SECOND_HOME_GAIN, IncomeTaxClass.SECTION_1250_GAIN,
                 IncomeTaxClass.COLLECTIBLES_GAINS, IncomeTaxClass.TAX_FREE ) ),
    _Grouping( 'rental', 'Rental Income', ( IncomeTaxClass.GROSS_RENTAL, ) ),
]
_SOURCE_BY_CLASS = { tax_class : ( order, source )
                     for order, source in enumerate( _INCOME_SOURCES )
                     for tax_class in source.classes }
# Within a subject, the tax-class accounts order by the tax class's own declaration order.
_TAX_CLASS_ORDER = { tax_class : index for index, tax_class in enumerate( IncomeTaxClass ) }


def stamp_display_placements( books : BooksOfAccount, profile : Profile ) -> None:
    """Stamp the books' accounts with their input grouping, best-effort. Each pass is guarded: a display
    concern must not be able to fail run capture, so a missing catalog or any error leaves that pass
    unstamped (the table then falls back to the engine-class grouping). The failure is logged, not
    silenced, so a broken mapping surfaces rather than invisibly degrading."""
    for stamp in ( lambda : _stamp_expense_placements( books ),
                   lambda : _stamp_income_placements( books, profile ),
                   lambda : _stamp_asset_placements( books, profile ) ):
        try:
            stamp()
        except Exception:
            logger.exception(
                'Display-placement stamping failed; those columns fall back to engine-class grouping.' )
            continue
        continue
    return


def _stamp_expense_placements( books : BooksOfAccount ) -> None:
    """Group each expense account under its ExpenseClass surface then its ExpenseCategory section. A
    catalog row supplies both for a catalog expense (matched on the base handle, so a property-scoped
    handle groups with its catalog kind while its per-property account stays distinct); the Vehicle
    pane's generated purchase and payment expenses carry no catalog row, so they map to the Vehicle
    section directly -- joining the catalog's vehicle running costs instead of falling back to their
    (Living) deductibility class."""
    catalog = { row.handle : row for row in ordered_catalog() }
    for account in books.accounts:
        if account.handle is None:
            continue
        base = _base_expense_handle( str( account.handle ) )
        row  = catalog.get( base )
        if row is not None:
            account.display_placement = _expense_placement(
                row.expense_class, row.category, row.order )
        elif base in _GENERATED_VEHICLE_ORDER:
            account.display_placement = _expense_placement(
                ExpenseClass.VEHICLE, ExpenseCategory.VEHICLE, _GENERATED_VEHICLE_ORDER[ base ] )
        continue
    return


def _expense_placement( expense_class, category, order ) -> AccountDisplayPlacement:
    """The two-rung expense placement: an ExpenseClass surface then an ExpenseCategory section, with
    `order` ranking the account within its section. Keyed by the enum names, so a catalog expense and a
    generated one that share a class and category land in the very same group."""
    return AccountDisplayPlacement(
        path = ( AccountDisplayGroup( key   = 'class-' + expense_class.name.lower(),
                                      label = expense_class.label,
                                      order = _CLASS_ORDER[ expense_class ] ),
                 AccountDisplayGroup( key   = 'cat-' + category.name.lower(),
                                      label = category.label,
                                      order = _CATEGORY_ORDER[ category ] ) ),
        order = order )


def _stamp_income_placements( books : BooksOfAccount, profile : Profile ) -> None:
    subjects = { subject.handle : ( index, subject.name )
                 for index, subject in enumerate( profile.subjects ) }
    for account in books.accounts:
        if account.income_tax_class is None:
            continue
        grouping = _SOURCE_BY_CLASS.get( account.income_tax_class )
        if grouping is None:
            continue
        source_order, source = grouping
        path = [ AccountDisplayGroup( key = source.key, label = source.label, order = source_order ) ]
        subject = subjects.get( str( account.owner_handle ) ) if account.owner_handle is not None else None
        if subject is not None:
            subject_order, subject_name = subject
            path.append( AccountDisplayGroup( key   = 'subj-' + str( account.owner_handle ),
                                              label = subject_name, order = subject_order ) )
        account.display_placement = AccountDisplayPlacement(
            path = tuple( path ), order = _TAX_CLASS_ORDER[ account.income_tax_class ] )
        continue
    return


def _stamp_asset_placements( books : BooksOfAccount, profile : Profile ) -> None:
    positions = { asset.handle : index for index, asset in enumerate( profile.assets ) }
    for account in books.accounts:
        if account.asset_class is None:
            continue
        grouping = _PANE_BY_CLASS.get( account.asset_class )
        if grouping is None:
            continue
        pane_order, pane = grouping
        leaf_order = ( positions.get( str( account.handle ), _UNMAPPED_ORDER )
                       if account.handle is not None else _UNMAPPED_ORDER )
        account.display_placement = AccountDisplayPlacement(
            path = ( AccountDisplayGroup( key = 'pane-' + pane.key, label = pane.label,
                                          order = pane_order ),
                     AccountDisplayGroup( key = account.asset_class.name,
                                          label = account.asset_class.label,
                                          order = _ASSET_CLASS_ORDER[ account.asset_class ] ) ),
            order = leaf_order )
        continue
    return
