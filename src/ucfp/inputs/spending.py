"""The spending section: the L0 category totals, the per-category dense editor, and the
catalog-to-plans seeding behind both.

§6 presents spending as a presumed annual total per applicable category, drawn from the curated
catalog, which the user accepts or drills into to adjust the individual expenses. This module
decides which categories apply from the plan's context, seeds the Plans' expense flows from the
catalog (preserving any amounts already set), and owns the annualization the totals use.
"""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional

from django import forms

from common.date_window import DateWindow
from common.recurrence import TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import WindowedAmount
from ucfp.inputs.widgets import IsoDateInput
from ucfp.parameter_sets.enums import CatalogScope, ExpenseCategory, ParameterSetKind
from ucfp.parameter_sets.repository import load
from ucfp.inputs.profile.schemas import RENT_OBLIGATION_HANDLE, RESIDENCE_ASSET_HANDLE
from ucfp.inputs.plans.schemas import ExpenseFlow
from ucfp.inputs.auto import AutoPlanForm

_WEEKS_PER_YEAR  = Decimal( '52' )
_MONTHS_PER_YEAR = Decimal( '12' )
_DAYS_PER_YEAR   = Decimal( '365' )

# Categories that always apply; the rest attach to a decision. Auto is presumed for now -- gated on
# a vehicle once a vehicle section exists.
_ALWAYS = ( ExpenseCategory.EVERYDAY, ExpenseCategory.DISCRETIONARY, ExpenseCategory.HEALTH,
            ExpenseCategory.AUTO )


def load_catalog():
    return load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )


@dataclass( frozen = True )
class SpendingGroup:
    """One row of the §6 spending list: a category, optionally scoped to a property (the residence
    for Home, a specific rental for Rental; None for the general living categories). Its `key`
    identifies the group in the URL and the inline editor's DOM, and its expenses are the merged
    flows matching both the category and the property."""
    category        : ExpenseCategory
    property_handle : Optional[ str ]
    label           : str

    @property
    def key( self ) -> str:
        base = self.category.name.lower()
        return base if self.property_handle is None else f'{base}-{self.property_handle}'


def applicable_categories( profile ) -> set:
    applicable  = set( _ALWAYS )
    assets      = { asset.handle for asset in profile.assets } if profile else set()
    obligations = (
        { obligation.handle for obligation in profile.obligations } if profile else set() )
    if RESIDENCE_ASSET_HANDLE in assets or RENT_OBLIGATION_HANDLE in obligations:
        applicable.add( ExpenseCategory.UTILITIES )
    if RESIDENCE_ASSET_HANDLE in assets:
        applicable.add( ExpenseCategory.HOME )
    if _rental_handles( profile ):
        applicable.add( ExpenseCategory.RENTAL )
    return applicable


def _rental_handles( profile ) -> list:
    return ( [ asset.handle for asset in profile.assets
               if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ] if profile else [] )


def _property_handles_for( category, profile ) -> list:
    """The property handles a category's operating expenses attach to: the residence for Home, each
    rental for Rental (one expense set per rental -- there may be several), and a single unbound
    `[None]` for the general living categories."""
    if category is ExpenseCategory.HOME:
        return [ RESIDENCE_ASSET_HANDLE ]
    if category is ExpenseCategory.RENTAL:
        return _rental_handles( profile )
    return [ None ]


def _property_name( profile, handle : str ) -> str:
    asset = next( ( a for a in profile.assets if a.handle == handle ), None )
    return asset.name if asset is not None else handle


def _group_label( category, property_handle, profile ) -> str:
    if category is ExpenseCategory.RENTAL:
        return f'Rental — {_property_name( profile, property_handle )}'
    return category.label


def spending_groups( profile ) -> list:
    """The §6 spending groups in display order: each applicable category, with Rental expanded to one
    group per rental property."""
    applicable = applicable_categories( profile )
    groups     = list()
    for category in ExpenseCategory:
        if category not in applicable:
            continue
        for handle in _property_handles_for( category, profile ):
            groups.append( SpendingGroup(
                category, handle, _group_label( category, handle, profile ) ) )
    return groups


def group_for_key( profile, key : str ) -> Optional[ SpendingGroup ]:
    return next( ( group for group in spending_groups( profile ) if group.key == key ), None )


def merged_expenses( profile, plans ) -> list:
    """The applicable catalog expenses as Plans expense flows -- existing amounts preserved, missing ones
    seeded at the catalog default, and no-longer-applicable categories dropped. A property-scoped
    category seeds one flow per attached property (each rental its own set), and the `property_handle`
    binding is re-derived every merge, since it is structural, not a user edit."""
    applicable = applicable_categories( profile )
    existing   = { ( expense.property_handle, expense.name ): expense
                   for expense in plans.expenses } if plans else dict()
    merged = list()
    for catalog_expense in load_catalog().expenses:
        if catalog_expense.category not in applicable:
            continue
        for handle in _property_handles_for( catalog_expense.category, profile ):
            flow = existing.get( ( handle, catalog_expense.name ) ) or _flow( catalog_expense )
            merged.append( replace( flow, property_handle = handle ) )
    return merged


def _flow( catalog_expense ) -> ExpenseFlow:
    return ExpenseFlow(
        name = catalog_expense.name, category = catalog_expense.category,
        expense_tax_class = catalog_expense.expense_tax_class,
        schedule = [ WindowedAmount( catalog_expense.default_amount ) ],
        interval = catalog_expense.interval,
        lifestyle_dependent = catalog_expense.lifestyle_dependent )


def current_amount( flow ) -> Decimal:
    """The amount in effect at the start of the plan -- the first (earliest) schedule row. The L0
    total shows what you spend now; the rest of the schedule lives in the drill."""
    return flow.schedule[ 0 ].amount if flow.schedule else Decimal( '0' )


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


def category_annual_total( expenses ) -> Decimal:
    total = Decimal( '0' )
    for expense in expenses:
        total += annual_amount( current_amount( expense ), expense.interval )
    return total


def cadence_label( interval ) -> str:
    if interval is None:
        return 'per year'
    if interval.count == 1:
        return f'per {interval.unit.label.lower()}'
    return f'every {interval.count} {interval.unit.label.lower()}s'


class SpendingForm:
    """§6 L0 -- spending as a presumed annual total per applicable category. The user accepts the
    defaults here and drills into a category to adjust its expenses. `apply` seeds the Plans'
    expense flows from the catalog for the applicable categories, preserving any amounts set."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile  = profile
        self._plans = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def auto_form( self ):
        """The car-ownership pane -- purchases and financing, edited and saved through `AutoPlanView`
        (the car purchase supersedes the old catalog line, so it lives here as its own structured
        input rather than among the catalog expenses)."""
        return AutoPlanForm( profile = self._profile, plans = self._plans )

    @property
    def group_totals( self ) -> list:
        """(group, annual total) per spending group, in display order -- Rental expanded per
        property."""
        all_expenses = merged_expenses( self._profile, self._plans )
        totals       = list()
        for group in spending_groups( self._profile ):
            expenses = [ expense for expense in all_expenses
                         if expense.category is group.category
                         and expense.property_handle == group.property_handle ]
            totals.append( ( group, category_annual_total( expenses ) ) )
        return totals

    def apply( self, profile, plans ):
        return profile, replace( plans, expenses = merged_expenses( profile, plans ) )


class GroupSpendingForm( forms.Form ):
    """The dense editor for one spending group -- per expense, a schedule of amount-over-span rows
    (`amount · start · end`), its existing rows plus one blank to add. `apply` rebuilds each
    expense's schedule from the filled rows, leaving the other groups' expenses untouched (a
    property-scoped group edits only its own property's expenses)."""

    _EXTRA_ROWS = 1

    def __init__( self, data = None, *, profile = None, plans = None, group = None ):
        super().__init__( data )
        self._all        = merged_expenses( profile, plans )
        self._expenses   = [ expense for expense in self._all
                             if expense.category is group.category
                             and expense.property_handle == group.property_handle ]
        self._row_counts = [ len( expense.schedule ) + self._EXTRA_ROWS
                             for expense in self._expenses ]
        for ei, expense in enumerate( self._expenses ):
            for ri in range( self._row_counts[ ei ] ):
                row = expense.schedule[ ri ] if ri < len( expense.schedule ) else None
                self._add_row_fields( ei, ri, row )

    def _add_row_fields( self, ei : int, ri : int, row ):
        amount = forms.DecimalField( required = False, min_value = 0 )
        start  = forms.DateField( required = False, widget = IsoDateInput() )
        end    = forms.DateField( required = False, widget = IsoDateInput() )
        if row is not None:
            amount.initial = row.amount
            start.initial  = row.window.start
            end.initial    = row.window.end
        self.fields[ self._key( ei, ri, 'amount' ) ] = amount
        self.fields[ self._key( ei, ri, 'start' ) ]  = start
        self.fields[ self._key( ei, ri, 'end' ) ]    = end

    @staticmethod
    def _key( ei : int, ri : int, part : str ) -> str:
        return f'e{ei}_r{ri}_{part}'

    @property
    def expense_rows( self ) -> list:
        blocks = list()
        for ei, expense in enumerate( self._expenses ):
            rows = [ { 'amount' : self[ self._key( ei, ri, 'amount' ) ],
                       'start'  : self[ self._key( ei, ri, 'start' ) ],
                       'end'    : self[ self._key( ei, ri, 'end' ) ] }
                     for ri in range( self._row_counts[ ei ] ) ]
            blocks.append( {
                'name': expense.name, 'cadence': cadence_label( expense.interval ), 'rows': rows } )
        return blocks

    @property
    def group_total( self ) -> Decimal:
        return category_annual_total( self._edited_expenses() )

    def apply( self, profile, plans ):
        edited   = { ( e.property_handle, e.name ): e for e in self._edited_expenses() }
        expenses = [ edited.get( ( e.property_handle, e.name ), e ) for e in self._all ]
        return profile, replace( plans, expenses = expenses )

    def _edited_expenses( self ) -> list:
        return [ replace( expense, schedule = self._schedule( ei ) )
                 for ei, expense in enumerate( self._expenses ) ]

    def _schedule( self, ei : int ) -> list:
        rows = list()
        for ri in range( self._row_counts[ ei ] ):
            amount = self.cleaned_data.get( self._key( ei, ri, 'amount' ) )
            if amount is None:
                continue
            window = DateWindow(
                start = self.cleaned_data.get( self._key( ei, ri, 'start' ) ),
                end = self.cleaned_data.get( self._key( ei, ri, 'end' ) ) )
            rows.append( WindowedAmount( amount, window ) )
        rows.sort( key = lambda windowed: windowed.window.start or date.min )
        return rows
