"""The spending section's form and the catalog-to-scenario seeding behind it.

§6 presents spending as a presumed total per applicable category, drawn from the curated expense
catalog. The user accepts the defaults here and adjusts by drilling into a category later, so there
is nothing to edit at this level. This module decides which categories apply from the plan's
context, seeds the scenario's expense flows from the catalog (preserving any amounts already set),
and owns the annualization the totals use.
"""
from dataclasses import replace
from decimal import Decimal

from common.recurrence import TimeUnit

from ucfp.parameter_sets.enums import CatalogScope, ExpenseCategory, ParameterSetKind
from ucfp.parameter_sets.repository import load
from ucfp.profile.schemas import RENT_OBLIGATION_HANDLE, RESIDENCE_ASSET_HANDLE
from ucfp.scenario.schemas import ExpenseFlow

_WEEKS_PER_YEAR  = Decimal( '52' )
_MONTHS_PER_YEAR = Decimal( '12' )
_DAYS_PER_YEAR   = Decimal( '365' )

# Categories that always apply; the rest attach to a decision. Auto is presumed for now -- gated on
# a vehicle once a vehicle section exists.
_ALWAYS = ( ExpenseCategory.EVERYDAY, ExpenseCategory.DISCRETIONARY, ExpenseCategory.HEALTH,
            ExpenseCategory.AUTO )


def _occurrences_per_year( interval ) -> Decimal:
    if interval.unit is TimeUnit.YEAR:
        return Decimal( 1 ) / interval.count
    if interval.unit is TimeUnit.MONTH:
        return _MONTHS_PER_YEAR / interval.count
    if interval.unit is TimeUnit.WEEK:
        return _WEEKS_PER_YEAR / interval.count
    return _DAYS_PER_YEAR / interval.count


def annual_amount( amount : Decimal, interval ) -> Decimal:
    """An expense's annual magnitude: a stream amount is already annual; an item amount is
    per-occurrence, so it scales by its occurrences per year."""
    if interval is None:
        return amount
    return amount * _occurrences_per_year( interval )


class SpendingForm:
    """§6 -- spending shown as a presumed total per applicable category, from the curated catalog.
    The user accepts the defaults here and drills into a category to adjust individual expenses (a
    later level), so there is nothing to edit at this level. `apply` seeds the scenario's expense
    flows from the catalog for the applicable categories, preserving any amounts already set."""

    def __init__( self, data = None, *, profile = None, scenario = None ):
        self._profile  = profile
        self._scenario = scenario
        self._catalog  = load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )

    def is_valid( self ) -> bool:
        return True

    @property
    def category_totals( self ) -> list:
        """(category, annual total) per applicable category, in catalog order, for display."""
        by_category = dict()
        for expense in self._merged_expenses():
            by_category.setdefault( expense.category, Decimal( '0' ) )
            by_category[ expense.category ] += annual_amount( expense.amount, expense.interval )
        return [ ( category, by_category[ category ] )
                 for category in ExpenseCategory if category in by_category ]

    def apply( self, profile, scenario ):
        return profile, replace( scenario, expenses = self._merged_expenses() )

    def _merged_expenses( self ) -> list:
        """The applicable catalog expenses as scenario flows -- existing amounts preserved, missing
        ones seeded at the catalog default, and no-longer-applicable categories dropped."""
        applicable = self._applicable_categories()
        existing   = { expense.name: expense for expense in self._scenario.expenses }
        merged = list()
        for catalog_expense in self._catalog.expenses:
            if catalog_expense.category not in applicable:
                continue
            merged.append( existing.get( catalog_expense.name ) or self._flow( catalog_expense ) )
        return merged

    @staticmethod
    def _flow( catalog_expense ) -> ExpenseFlow:
        return ExpenseFlow(
            name = catalog_expense.name, category = catalog_expense.category,
            expense_tax_class = catalog_expense.expense_tax_class,
            amount = catalog_expense.default_amount, interval = catalog_expense.interval,
            lifestyle_dependent = catalog_expense.lifestyle_dependent )

    def _applicable_categories( self ) -> set:
        applicable  = set( _ALWAYS )
        assets      = { asset.handle for asset in self._profile.assets } if self._profile else set()
        obligations = (
            { obligation.handle for obligation in self._profile.obligations }
            if self._profile else set() )
        owns_home = RESIDENCE_ASSET_HANDLE in assets
        rents     = RENT_OBLIGATION_HANDLE in obligations
        if owns_home or rents:
            applicable.add( ExpenseCategory.UTILITIES )
        if owns_home:
            applicable.add( ExpenseCategory.HOME )
        return applicable
