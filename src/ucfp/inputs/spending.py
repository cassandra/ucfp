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
from ucfp.parameter_sets.enums import CatalogScope, ExpenseCategory, ParameterSetKind, PropertyContext
from ucfp.parameter_sets.repository import load
from ucfp.inputs.profile.schemas import RENT_OBLIGATION_HANDLE
from ucfp.inputs.plans.schemas import ExpenseFlow, RecurringExpense
from ucfp.inputs.auto import AutoPlanForm

_WEEKS_PER_YEAR  = Decimal( '52' )
_MONTHS_PER_YEAR = Decimal( '12' )
_DAYS_PER_YEAR   = Decimal( '365' )

# Categories that always apply; Property attaches to owning or renting a dwelling. Auto is presumed
# for now -- gated on a vehicle once a vehicle section exists.
_ALWAYS = ( ExpenseCategory.EVERYDAY, ExpenseCategory.DISCRETIONARY, ExpenseCategory.HEALTH,
            ExpenseCategory.AUTO, ExpenseCategory.MISCELLANEOUS )

# An owned real-property holding's asset class, mapped to the property context its expenses seed
# against. A tenant's rented home (the rent obligation) maps to RENTED_HOME separately.
_OWNED_PROPERTY_CONTEXT = {
    AssetClass.REAL_ESTATE_RESIDENCE   : PropertyContext.RESIDENCE,
    AssetClass.REAL_ESTATE_SECOND_HOME : PropertyContext.SECOND_HOME,
    AssetClass.REAL_ESTATE_RENTAL      : PropertyContext.RENTAL,
}


def load_catalog():
    return load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )


@dataclass( frozen = True )
class SpendingGroup:
    """One row of the §6 spending list: a category, optionally scoped to a property -- one owned
    dwelling (or the rented home) for Property, None for the household categories. Its `key`
    identifies the group in the URL and the inline editor's DOM, and its expenses are the merged
    flows matching both the category and the property."""
    category        : ExpenseCategory
    property_handle : Optional[ str ]
    label           : str

    @property
    def key( self ) -> str:
        base = self.category.name.lower()
        return base if self.property_handle is None else f'{base}-{self.property_handle}'

    @property
    def is_property( self ) -> bool:
        """Whether this group's expenses are property operating costs (drillable into the schedule
        editor). The regular categories are recurring expenses, edited elsewhere."""
        return self.category is ExpenseCategory.PROPERTY


def applicable_categories( profile ) -> set:
    """The categories that apply to this profile: the always-on set, plus Property if the household
    owns any real property or rents its home."""
    applicable = set( _ALWAYS )
    if _owned_property_handles( profile ) or _renting( profile ):
        applicable.add( ExpenseCategory.PROPERTY )
    return applicable


def _owned_property_handles( profile ) -> list:
    """The handles of owned real property -- residence, then second homes, then rentals (display
    order); one Property expense set attaches to each."""
    if profile is None:
        return []
    order = { asset_class: index for index, asset_class in enumerate( _OWNED_PROPERTY_CONTEXT ) }
    owned = [ asset for asset in profile.assets if asset.asset_class in _OWNED_PROPERTY_CONTEXT ]
    owned.sort( key = lambda asset: ( order[ asset.asset_class ], asset.handle ) )
    return [ asset.handle for asset in owned ]


def _renting( profile ) -> bool:
    return profile is not None and any(
        obligation.handle == RENT_OBLIGATION_HANDLE for obligation in profile.obligations )


def _asset_for( profile, handle : str ):
    return next( ( asset for asset in profile.assets if asset.handle == handle ), None )


def _property_context( profile, handle : str ) -> Optional[ PropertyContext ]:
    """The `PropertyContext` a Property handle represents: a tenant's rented home for the rent
    obligation, else the owned holding's class mapped to its context (None if not real property)."""
    if handle == RENT_OBLIGATION_HANDLE:
        return PropertyContext.RENTED_HOME
    asset = _asset_for( profile, handle )
    return _OWNED_PROPERTY_CONTEXT.get( asset.asset_class ) if asset is not None else None


def _property_handles_for( category, profile ) -> list:
    """The handles a category's expenses attach to: each owned property -- and, when the household
    rents, its rented home -- for Property (one expense set per handle), and a single unbound `[None]`
    for the household categories."""
    if category is not ExpenseCategory.PROPERTY:
        return [ None ]
    handles = _owned_property_handles( profile )
    return handles + [ RENT_OBLIGATION_HANDLE ] if _renting( profile ) else handles


def _property_name( profile, handle : str ) -> str:
    asset = _asset_for( profile, handle )
    return asset.name if asset is not None else handle


# The display label for each property context. The household's single home -- owned (RESIDENCE) or
# rented (RENTED_HOME) -- is a bare label; a SECOND_HOME or RENTAL is one of several, so its own name
# is appended (see `_group_label`).
_PROPERTY_CONTEXT_LABEL = {
    PropertyContext.RESIDENCE   : 'Home',
    PropertyContext.RENTED_HOME : 'Home (rented)',
    PropertyContext.SECOND_HOME : 'Second home',
    PropertyContext.RENTAL      : 'Rental',
}
_NAMED_CONTEXTS = ( PropertyContext.SECOND_HOME, PropertyContext.RENTAL )


def _group_label( category, property_handle, profile ) -> str:
    if category is not ExpenseCategory.PROPERTY:
        return category.label
    context = _property_context( profile, property_handle )
    label   = _PROPERTY_CONTEXT_LABEL.get( context, 'Property' )
    if context in _NAMED_CONTEXTS:
        return f'{label} — {_property_name( profile, property_handle )}'
    return label


def spending_groups( profile ) -> list:
    """The §6 spending groups in display order: each applicable category, with Property expanded to
    one group per owned dwelling (and the rented home, when renting)."""
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
    """The applicable PROPERTY operating expenses as Plans expense flows -- one flow per attached
    dwelling, existing schedules preserved and missing ones seeded at the catalog default, skipping
    rows whose `applies_to` does not cover that property's context. The structural bindings --
    `property_handle`, `category`, and the personal `expense_tax_class` (materialization derives the
    rental swap) -- are re-derived every merge, since they are not user edits; only the schedule amounts
    are preserved. Regular (non-property) recurring expenses are a separate class -- see
    `merged_recurring_expenses`."""
    if ExpenseCategory.PROPERTY not in applicable_categories( profile ):
        return list()
    existing = { ( expense.property_handle, expense.name ): expense
                 for expense in plans.expenses } if plans else dict()
    merged = list()
    for catalog_expense in load_catalog().expenses:
        if catalog_expense.category is not ExpenseCategory.PROPERTY:
            continue
        for handle in _property_handles_for( catalog_expense.category, profile ):
            if not _row_seeds( catalog_expense, profile, handle ):
                continue
            flow = existing.get( ( handle, catalog_expense.name ) ) or _flow( catalog_expense )
            merged.append( replace(
                flow, property_handle = handle, category = catalog_expense.category,
                expense_tax_class = catalog_expense.expense_tax_class ) )
    return merged


def merged_recurring_expenses( profile, plans ) -> list:
    """The applicable regular (non-property) catalog expenses as `RecurringExpense`s -- existing amounts
    preserved (aligned to the plan's span count), missing ones seeded at the catalog default across
    every span. The category and personal tax class are re-derived each merge (not user edits)."""
    applicable = applicable_categories( profile )
    span_count = len( plans.expense_spans ) if plans and plans.expense_spans else 1
    existing   = { expense.name: expense
                   for expense in plans.recurring_expenses } if plans else dict()
    merged = list()
    for catalog_expense in load_catalog().expenses:
        if ( catalog_expense.category is ExpenseCategory.PROPERTY
                or catalog_expense.category not in applicable ):
            continue
        merged.append( RecurringExpense(
            name = catalog_expense.name, category = catalog_expense.category,
            expense_tax_class = catalog_expense.expense_tax_class,
            amounts = _aligned_amounts(
                existing.get( catalog_expense.name ), catalog_expense.default_amount, span_count ),
            interval = catalog_expense.interval ) )
    return merged


def _aligned_amounts( prior, default : Decimal, span_count : int ) -> list:
    """`prior`'s amounts padded (with its last) or truncated to `span_count`, or the catalog `default`
    across every span when there is no prior expense."""
    if prior is None:
        return [ default ] * span_count
    amounts = list( prior.amounts )
    if len( amounts ) < span_count:
        amounts += [ amounts[ -1 ] if amounts else default ] * ( span_count - len( amounts ) )
    return amounts[ :span_count ]


def _row_seeds( catalog_expense, profile, handle ) -> bool:
    """Whether a catalog row seeds a flow for this handle. A household row always does; a Property row
    seeds only the property contexts in its `applies_to` -- so property management skips a residence,
    and only utilities reach a rented home."""
    if catalog_expense.category is not ExpenseCategory.PROPERTY:
        return True
    return _property_context( profile, handle ) in catalog_expense.applies_to


def _flow( catalog_expense ) -> ExpenseFlow:
    return ExpenseFlow(
        name = catalog_expense.name, category = catalog_expense.category,
        expense_tax_class = catalog_expense.expense_tax_class,
        schedule = [ WindowedAmount( catalog_expense.default_amount ) ],
        interval = catalog_expense.interval )


def current_amount( flow ) -> Decimal:
    """The amount in effect at the start of the plan -- the first (earliest) schedule row. The L0
    total shows what you spend now; the rest of the schedule lives in the drill."""
    return flow.schedule[ 0 ].amount if flow.schedule else Decimal( '0' )


def recurring_current_amount( expense ) -> Decimal:
    """A recurring expense's amount in the first span -- what it costs now."""
    return expense.amounts[ 0 ] if expense.amounts else Decimal( '0' )


def recurring_annual_total( expenses ) -> Decimal:
    return sum(
        ( annual_amount( recurring_current_amount( e ), e.interval ) for e in expenses ),
        Decimal( '0' ) )


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
        """The car-ownership pane -- purchases and financing, edited and saved through `AutoPlanView`.
        The car purchase is its own structured input here rather than a catalog expense, since it is
        large and sometimes financed."""
        return AutoPlanForm( profile = self._profile, plans = self._plans )

    @property
    def group_totals( self ) -> list:
        """(group, annual total) per spending group, in display order -- Property expanded per owned
        dwelling. Property groups total their schedule-based flows; the regular categories total their
        recurring expenses (their first-span amount)."""
        property_expenses = merged_expenses( self._profile, self._plans )
        recurring         = merged_recurring_expenses( self._profile, self._plans )
        totals            = list()
        for group in spending_groups( self._profile ):
            if group.category is ExpenseCategory.PROPERTY:
                expenses = [ e for e in property_expenses
                             if e.property_handle == group.property_handle ]
                totals.append( ( group, category_annual_total( expenses ) ) )
            else:
                expenses = [ e for e in recurring if e.category is group.category ]
                totals.append( ( group, recurring_annual_total( expenses ) ) )
        return totals

    def apply( self, profile, plans ):
        return profile, replace(
            plans,
            expenses = merged_expenses( profile, plans ),
            recurring_expenses = merged_recurring_expenses( profile, plans ) )


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
