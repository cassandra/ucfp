"""The spending section: the recurring-expenses table, the per-property operating costs, and the
catalog-to-plans seeding behind both.

§6 presents spending drawn from the curated catalog: the regular categories as a recurring-expenses
table over the shared age-span timeline, and the household's property operating costs as one shared
default with per-property overrides, edited as a matrix (expense types down, properties across). This
module decides which categories/properties apply from the plan's context and seeds the Plans' expenses
from the catalog, preserving any amounts already set.
"""
from dataclasses import replace
from decimal import Decimal
from typing import Optional

from django import forms

from ucfp.accounts.enums import AssetClass
from ucfp.parameter_sets.enums import CatalogScope, ExpenseCategory, ParameterSetKind, PropertyContext
from ucfp.parameter_sets.repository import load
from ucfp.inputs.profile.schemas import RENT_OBLIGATION_HANDLE
from ucfp.inputs.plans.schemas import PropertyExpense, RecurringExpense
from ucfp.inputs.auto import AutoPlanForm

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


def merged_property_expenses( profile, plans ) -> list:
    """The catalog's PROPERTY expenses as `PropertyExpense`s -- one per catalog row, its structural
    fields (category, personal tax class, cadence, `applies_to`) re-derived each merge; the user's
    `default_amount` and per-property `overrides` preserved, with overrides pruned to the properties
    that currently exist and that the row applies to. Empty when the household has no property."""
    if ExpenseCategory.PROPERTY not in applicable_categories( profile ):
        return list()
    existing     = { expense.name: expense for expense in plans.property_expenses } if plans else dict()
    live_handles = set( _property_handles_for( ExpenseCategory.PROPERTY, profile ) )
    merged = list()
    for catalog_expense in load_catalog().expenses:
        if catalog_expense.category is not ExpenseCategory.PROPERTY:
            continue
        prior = existing.get( catalog_expense.name )
        merged.append( PropertyExpense(
            name = catalog_expense.name, category = catalog_expense.category,
            expense_tax_class = catalog_expense.expense_tax_class,
            applies_to = catalog_expense.applies_to, interval = catalog_expense.interval,
            default_amount = prior.default_amount if prior is not None else catalog_expense.default_amount,
            overrides = _live_overrides( prior, profile, catalog_expense, live_handles ) ) )
    return merged


def _live_overrides( prior, profile, catalog_expense, live_handles : set ) -> dict:
    """A prior property expense's overrides kept only for properties that still exist and that the row
    applies to; empty when there is no prior expense."""
    if prior is None:
        return dict()
    return { handle: amount for handle, amount in prior.overrides.items()
             if handle in live_handles
             and _property_context( profile, handle ) in catalog_expense.applies_to }


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
    def recurring_form( self ):
        """The editable recurring-expenses table (the regular, non-property categories over the shared
        span timeline), saved on its own through `RecurringExpensesView`."""
        return RecurringExpensesForm( profile = self._profile, plans = self._plans )

    @property
    def property_form( self ):
        """The editable property-expenses matrix (the household's per-property operating costs as one
        shared default with per-property overrides), saved on its own through `PropertyExpensesView`.
        Empty of rows when the household has no property, in which case the section hides it."""
        return PropertyExpensesForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, replace(
            plans,
            property_expenses = merged_property_expenses( profile, plans ),
            recurring_expenses = merged_recurring_expenses( profile, plans ) )


class RecurringExpensesForm( forms.Form ):
    """The recurring-expenses table: rows are the regular (non-property) expenses grouped by category,
    columns are the spans of the shared timeline. Each span carries an "until age" (the last blank, the
    open "thereafter" span); each cell is an amount at the row's cadence. Filling the open span's age
    splits it (a new open span duplicates it); clearing a span's age deletes that span. Ages are the
    primary subject's. `apply` writes the shared `expense_spans` and every recurring expense's per-span
    amounts; `spans_changed` reports when the span set changed, so the pane re-renders."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._birthdate = ( profile.subjects[ 0 ].birthdate
                            if profile is not None and profile.subjects else None )
        self._expenses  = merged_recurring_expenses( profile, plans )
        self._spans     = list( plans.expense_spans ) if plans and plans.expense_spans else [ None ]
        for si, until in enumerate( self._spans ):
            field = forms.IntegerField( required = False, min_value = 0 )
            field.initial = until
            self.fields[ self._until_key( si ) ] = field
        for ei, expense in enumerate( self._expenses ):
            for si in range( len( self._spans ) ):
                cell = forms.DecimalField( required = False, min_value = 0 )
                cell.initial = expense.amounts[ si ] if si < len( expense.amounts ) else (
                    expense.amounts[ -1 ] if expense.amounts else None )
                self.fields[ self._amount_key( ei, si ) ] = cell

    @staticmethod
    def _until_key( si : int ) -> str:
        return f'until_{si}'

    @staticmethod
    def _amount_key( ei : int, si : int ) -> str:
        return f'amt_{ei}_{si}'

    @property
    def span_count( self ) -> int:
        return len( self._spans )

    @property
    def span_headers( self ) -> list:
        """The 'until age' header field per span, with the calendar year the primary reaches that age
        (when a birthdate is known) -- the last span's age is blank (the open 'thereafter')."""
        headers = list()
        for si, until in enumerate( self._spans ):
            year = ( self._birthdate.year + until
                     if until is not None and self._birthdate is not None else None )
            headers.append( { 'field': self[ self._until_key( si ) ], 'year': year } )
        return headers

    @property
    def sections( self ) -> list:
        """The expense rows grouped by category (a section header per category), each row its name,
        cadence, and one amount cell per span."""
        sections, current = list(), None
        for ei, expense in enumerate( self._expenses ):
            if expense.category is not current:
                current = expense.category
                sections.append( { 'label': current.label, 'rows': list() } )
            sections[ -1 ][ 'rows' ].append( {
                'name'    : expense.name,
                'cadence' : cadence_label( expense.interval ),
                'cells'   : [ self[ self._amount_key( ei, si ) ]
                              for si in range( len( self._spans ) ) ] } )
        return sections

    def apply( self, profile, plans ):
        columns  = self._columns()
        spans    = [ until for until, _ in columns ]
        expenses = [ replace( expense, amounts = [ amounts[ ei ] for _, amounts in columns ] )
                     for ei, expense in enumerate( self._expenses ) ]
        return profile, replace( plans, expense_spans = spans, recurring_expenses = expenses )

    def spans_changed( self ) -> bool:
        """Whether the applied span timeline differs from the current one -- a span added, removed, or
        re-aged -- so the pane must re-render; a pure amount edit leaves it unchanged (a silent save)."""
        return [ until for until, _ in self._columns() ] != list( self._spans )

    def _columns( self ) -> list:
        """The edited (until_age, [amount per expense]) columns after this POST's one structural action,
        if any: an explicit column delete (a row's ×) or splitting the open span (giving it an age).
        The last column is always the open 'thereafter' span -- deleting the open span leaves the new
        last ageless (so it becomes the thereafter). A non-last span left ageless is dropped, keeping
        the timeline continuous. Ordered by age, the open span last."""
        cleaned = self.cleaned_data
        columns = [ [ cleaned.get( self._until_key( si ) ),
                      [ cleaned.get( self._amount_key( ei, si ) ) or Decimal( '0' )
                        for ei in range( len( self._expenses ) ) ] ]
                    for si in range( len( self._spans ) ) ]
        delete = self._delete_index()
        if delete is not None and 0 <= delete < len( columns ):
            del columns[ delete ]                          # the row's × control
        elif columns and columns[ -1 ][ 0 ] is not None:
            columns.append( [ None, list( columns[ -1 ][ 1 ] ) ] )   # split the open span
        if not columns:
            columns = [ [ None, [ Decimal( '0' ) ] * len( self._expenses ) ] ]
        columns[ -1 ][ 0 ] = None                          # the last span is always the open one
        kept = [ ( until, amounts ) for index, ( until, amounts ) in enumerate( columns )
                 if until is not None or index == len( columns ) - 1 ]
        kept.sort( key = lambda column: ( column[ 0 ] is None, column[ 0 ] or 0 ) )
        return kept

    def _delete_index( self ):
        """The span index the row's × control asked to delete (a raw `delete_span` field, not a form
        field), or None when this save carried no delete."""
        try:
            return int( ( self.data or {} ).get( 'delete_span' ) )
        except ( TypeError, ValueError ):
            return None


class PropertyExpensesForm( forms.Form ):
    """The property-expenses matrix: rows are the property operating-cost types (property tax,
    insurance, ...), columns are the shared Default plus one per property (owned dwellings, then the
    rented home). The Default cell sets the amount every applicable property inherits; a per-property
    cell overrides it (blank falls back to the default, shown as its placeholder). A cell is N/A where
    the row does not apply to that property's context, and a row is shown only when it applies to at
    least one property the household has. With a single property the Default column collapses into one
    value column: it shows that property's effective amount and saves it as the shared default.

    `apply` writes back every property expense -- the displayed rows updated from the matrix, the rest
    (rows for property kinds the household lacks) passed through so their latent amounts survive. The
    row and column sets change only when a property is added or removed (done in the Property section),
    so this pane saves silently and never restructures itself."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile   = profile
        self._all       = merged_property_expenses( profile, plans )
        self._handles   = _property_handles_for( ExpenseCategory.PROPERTY, profile )
        self._rows      = [ expense for expense in self._all if self._any_applicable( expense ) ]
        self._collapsed = len( self._handles ) <= 1
        for ri, expense in enumerate( self._rows ):
            default = forms.DecimalField( required = False, min_value = 0 )
            default.initial = self._collapsed_value( expense ) if self._collapsed else expense.default_amount
            default.widget.attrs[ 'placeholder' ] = '0'
            self.fields[ self._default_key( ri ) ] = default
            if self._collapsed:
                continue
            for hi, handle in enumerate( self._handles ):
                if not self._applies( expense, handle ):
                    continue
                override = forms.DecimalField( required = False, min_value = 0 )
                override.initial = expense.overrides.get( handle )
                override.widget.attrs[ 'placeholder' ] = self._placeholder( expense.default_amount )
                self.fields[ self._override_key( ri, hi ) ] = override

    @staticmethod
    def _default_key( ri : int ) -> str:
        return f'default_{ri}'

    @staticmethod
    def _override_key( ri : int, hi : int ) -> str:
        return f'override_{ri}_{hi}'

    def _applies( self, expense, handle : str ) -> bool:
        return _property_context( self._profile, handle ) in expense.applies_to

    def _any_applicable( self, expense ) -> bool:
        return any( self._applies( expense, handle ) for handle in self._handles )

    def _collapsed_value( self, expense ) -> Optional[ Decimal ]:
        """The single property's effective amount -- its override if it set one, else the shared default
        -- so the collapsed one-column view shows what actually applies before it is saved as the
        default."""
        handle = self._handles[ 0 ]
        return expense.overrides.get( handle, expense.default_amount )

    @staticmethod
    def _placeholder( default : Optional[ Decimal ] ) -> str:
        """A per-property cell's placeholder: the shared default it falls back to when left blank, or
        '0' when the default itself is blank (the expense is then not charged)."""
        return str( default ) if default is not None else '0'

    @property
    def collapsed( self ) -> bool:
        """Whether the Default column has collapsed into a single value column (the household has at most
        one property), so the help text drops the shared-default/override language."""
        return self._collapsed

    @property
    def columns( self ) -> list:
        """The header cells: a single value column (the lone property's name) when collapsed, otherwise
        the shared 'Default' followed by one column per property."""
        if self._collapsed:
            label = self._column_label( self._handles[ 0 ] ) if self._handles else 'Amount'
            return [ { 'label': label, 'is_default': True } ]
        columns = [ { 'label': 'Default', 'is_default': True } ]
        columns += [ { 'label': self._column_label( handle ), 'is_default': False }
                     for handle in self._handles ]
        return columns

    def _column_label( self, handle : str ) -> str:
        return _group_label( ExpenseCategory.PROPERTY, handle, self._profile )

    @property
    def rows( self ) -> list:
        """One row per displayed expense: its name, cadence, and a cell per column -- the bound Default
        field, then each property's override field, or None where the row is N/A for that property."""
        result = list()
        for ri, expense in enumerate( self._rows ):
            cells = [ self[ self._default_key( ri ) ] ]
            if not self._collapsed:
                cells += [ self[ self._override_key( ri, hi ) ]
                           if self._override_key( ri, hi ) in self.fields else None
                           for hi in range( len( self._handles ) ) ]
            result.append( {
                'name'    : expense.name,
                'cadence' : cadence_label( expense.interval ),
                'cells'   : cells } )
        return result

    def apply( self, profile, plans ):
        edited   = { expense.name: self._edited( ri, expense )
                     for ri, expense in enumerate( self._rows ) }
        expenses = [ edited.get( expense.name, expense ) for expense in self._all ]
        return profile, replace( plans, property_expenses = expenses )

    def _edited( self, ri : int, expense ) -> PropertyExpense:
        """`expense` with its default and overrides taken from the matrix. Collapsed, the one column is
        the shared default and overrides are cleared; otherwise the Default cell is the default and each
        filled property cell an override (a blank cell drops back to the default)."""
        cleaned = self.cleaned_data
        default = cleaned.get( self._default_key( ri ) )
        if self._collapsed:
            return replace( expense, default_amount = default, overrides = dict() )
        overrides = dict()
        for hi, handle in enumerate( self._handles ):
            key = self._override_key( ri, hi )
            if key in self.fields and cleaned.get( key ) is not None:
                overrides[ handle ] = cleaned[ key ]
        return replace( expense, default_amount = default, overrides = overrides )
