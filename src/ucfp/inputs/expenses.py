"""Shared expense-catalog plumbing the Home and Living expense steps both build on.

It loads the curated catalog, decides which properties apply to a household, and keeps a merged
expense's cadence in step with the catalog. No forms and no view: each step owns its own pane
(`property_expenses`, `recurring_expenses`); this holds only what the two genuinely share. Which surface
a catalog row belongs to is its `ExpenseClass` (each step filters on it); the cadence *control* (its
editor and label) lives in `cadence`.
"""
from ucfp.accounts.enums import AssetClass
from ucfp.parameter_sets.enums import (
    CatalogScope, ExpenseCategory, ParameterSetKind, PropertyContext )
from ucfp.parameter_sets.repository import load
from ucfp.inputs.profile.enums import HousingTenure

# An owned real-property holding's asset class, mapped to the property context its expenses seed
# against. A tenant's rented home maps to RENTED_HOME separately (see `is_renting`).
OWNED_PROPERTY_CONTEXT = {
    AssetClass.REAL_ESTATE_RESIDENCE   : PropertyContext.RESIDENCE,
    AssetClass.REAL_ESTATE_SECOND_HOME : PropertyContext.SECOND_HOME,
    AssetClass.REAL_ESTATE_RENTAL      : PropertyContext.RENTAL,
}


def load_catalog():
    return load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )


def ordered_catalog() -> list:
    """The catalog's expense types in the deliberate (group, item) order -- sorted by (category
    declaration order, per-item `order`). Every spending surface seeds from this, so their rows share one
    ordering, independent of how the catalog source happens to be authored."""
    rank = { category : index for index, category in enumerate( ExpenseCategory ) }
    return sorted( load_catalog().expenses, key = lambda expense: ( rank[ expense.category ], expense.order ) )


def grouped_sections( items ) -> list:
    """Group an ordered iterable of `(category, row)` pairs into `[{ category, label, rows }]` sections --
    a new section each time the category changes. The items must already be in the deliberate order (from
    a merge that seeded through `ordered_catalog`), so same-category rows are contiguous. The shared
    section grouping both spending tables render by."""
    sections = list()
    for category, row in items:
        if not sections or sections[ -1 ][ 'category' ] is not category:
            sections.append( { 'category': category, 'label': category.label, 'rows': list() } )
        sections[ -1 ][ 'rows' ].append( row )
    return sections


def owned_property_handles( profile ) -> list:
    """The handles of owned real property -- residence, then second homes, then rentals (display
    order); one Property expense set attaches to each."""
    if profile is None:
        return []
    order = { asset_class: index for index, asset_class in enumerate( OWNED_PROPERTY_CONTEXT ) }
    owned = [ asset for asset in profile.assets if asset.asset_class in OWNED_PROPERTY_CONTEXT ]
    owned.sort( key = lambda asset: ( order[ asset.asset_class ], asset.handle ) )
    return [ asset.handle for asset in owned ]


def is_renting( profile ) -> bool:
    return profile is not None and profile.home_tenure is HousingTenure.RENT


def has_property( profile ) -> bool:
    """Whether the household has any dwelling with operating costs -- an owned property or a rented
    home -- so the Home Expenses step (and its matrix) applies."""
    return bool( owned_property_handles( profile ) ) or is_renting( profile )


def kept_interval( prior, catalog_expense ):
    """The cadence to seed on a merge: the prior expense's `interval` when it has one (a preserved user
    edit), else the catalog default. Only the cadence is a user edit -- the realization is fixed and
    always re-derived from the catalog."""
    if prior is not None and prior.interval is not None:
        return prior.interval
    return catalog_expense.interval


def kept_attr( prior, catalog_expense, attr : str ):
    """A user-editable value preserved across a merge: the prior expense's when set, else the catalog's
    (e.g. a durable's `count` / `cost_each` calculator inputs)."""
    value = getattr( prior, attr ) if prior is not None else None
    return value if value is not None else getattr( catalog_expense, attr )
