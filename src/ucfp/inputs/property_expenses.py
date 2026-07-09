"""Home Expenses -- the household's per-property operating costs as an editable matrix.

The step presents the catalog's PROPERTY expenses (property tax, insurance, utilities, rent, ...) as
one shared default with per-property overrides, expense types down the rows and properties across the
columns. This module seeds those expenses from the catalog (preserving amounts already set), owns the
property-identity/labeling helpers the matrix reads, and drives the self-saving pane.
"""
from dataclasses import replace
from decimal import Decimal
from typing import Optional

from django import forms

from ucfp.environment.constants import AppConst
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext
from ucfp.inputs.profile.schemas import RENTED_HOME_HANDLE
from ucfp.inputs.plans.schemas import PropertyExpense
from ucfp.inputs.expenses import (
    OWNED_PROPERTY_CONTEXT, applicable_categories, cadence_label, is_renting, load_catalog,
    owned_property_handles )


def _asset_for( profile, handle : str ):
    return next( ( asset for asset in profile.assets if asset.handle == handle ), None )


def _property_context( profile, handle : str ) -> Optional[ PropertyContext ]:
    """The `PropertyContext` a Property handle represents: a tenant's rented home for the synthetic
    rented-home handle, else the owned holding's class mapped to its context (None if not real
    property)."""
    if handle == RENTED_HOME_HANDLE:
        return PropertyContext.RENTED_HOME
    asset = _asset_for( profile, handle )
    return OWNED_PROPERTY_CONTEXT.get( asset.asset_class ) if asset is not None else None


def _property_handles_for( profile ) -> list:
    """The property columns in display order: the household's home first -- its owned residence, or,
    when it rents, the rented home -- then second homes and rentals (`owned_property_handles` already
    orders owned holdings)."""
    owned = owned_property_handles( profile )
    return [ RENTED_HOME_HANDLE ] + owned if is_renting( profile ) else owned


def _property_name( profile, handle : str ) -> str:
    asset = _asset_for( profile, handle )
    return asset.name if asset is not None else handle


# The display label for each property context. The household's single home -- owned (RESIDENCE) or
# rented (RENTED_HOME) -- is a bare label; a SECOND_HOME or RENTAL is one of several, so its own name
# is appended (see `_column_label`).
_PROPERTY_CONTEXT_LABEL = {
    PropertyContext.RESIDENCE   : 'Home',
    PropertyContext.RENTED_HOME : 'Home (rented)',
    PropertyContext.SECOND_HOME : 'Second home',
    PropertyContext.RENTAL      : 'Rental',
}
_NAMED_CONTEXTS = ( PropertyContext.SECOND_HOME, PropertyContext.RENTAL )


def _column_label( profile, handle : str ) -> str:
    context = _property_context( profile, handle )
    label   = _PROPERTY_CONTEXT_LABEL.get( context, 'Property' )
    if context in _NAMED_CONTEXTS:
        return f'{label} — {_property_name( profile, handle )}'
    return label


def merged_property_expenses( profile, plans ) -> list:
    """The catalog's PROPERTY expenses as `PropertyExpense`s -- one per catalog row, its structural
    fields (category, personal tax class, cadence, `applies_to`) re-derived each merge; the user's
    `default_amount` and per-property `overrides` preserved, with overrides pruned to the properties
    that currently exist and that the row applies to. Empty when the household has no property."""
    if ExpenseCategory.PROPERTY not in applicable_categories( profile ):
        return list()
    existing     = { expense.name: expense for expense in plans.property_expenses } if plans else dict()
    live_handles = set( _property_handles_for( profile ) )
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
        self._handles   = _property_handles_for( profile )
        self._rows      = [ expense for expense in self._all if self._any_applicable( expense ) ]
        self._collapsed = len( self._handles ) <= 1
        for ri, expense in enumerate( self._rows ):
            default = forms.DecimalField( required = False, min_value = 0 )
            default.initial = self._collapsed_value( expense ) if self._collapsed else expense.default_amount
            default.widget.attrs[ 'placeholder' ] = '0'
            default.widget.attrs[ 'class' ] = AppConst.PROPERTY_DEFAULT_CLASS
            self.fields[ self._default_key( ri ) ] = default
            if self._collapsed:
                continue
            for hi, handle in enumerate( self._handles ):
                if not self._applies( expense, handle ):
                    continue
                override = forms.DecimalField( required = False, min_value = 0 )
                override.initial = expense.overrides.get( handle )
                override.widget.attrs[ 'placeholder' ] = self._placeholder( expense.default_amount )
                override.widget.attrs[ 'class' ] = AppConst.PROPERTY_OVERRIDE_CLASS
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
            label = _column_label( self._profile, self._handles[ 0 ] ) if self._handles else 'Amount'
            return [ { 'label': label, 'is_default': True } ]
        columns = [ { 'label': 'Default', 'is_default': True } ]
        columns += [ { 'label': _column_label( self._profile, handle ), 'is_default': False }
                     for handle in self._handles ]
        return columns

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
