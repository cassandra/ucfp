"""Shapes a captured `TaxDisplayWorksheet` into a render model for the tax worksheet page.

The worksheet is a neutral table (column groups, columns, per-year rows). This turns it into what the
template draws: the two header rows (the group / income-sub-group spans, then the column labels), the body
rows with each cell already formatted for its column's units, and -- the one piece of display logic worth
testing -- the dropping of any column that is zero or blank in every year of the run, so an empty column
(a tax layer or income source this household never touches) never reaches the page.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ucfp.jurisdiction.tax_worksheet import (
    Column, ColumnCategory, ColumnFormat, TaxDisplayWorksheet )

# The category color classes -- the same blue / green / red / orange the books table tints its groups with
# (see css/tax_worksheet.css, which mirrors the books table's asset / revenue / liability / expense hues).
_CATEGORY_CSS = {
    ColumnCategory.INCOME: 'tw-cat-income',
    ColumnCategory.INCOME_DERIVED: 'tw-cat-income-derived',
    ColumnCategory.TAXES: 'tw-cat-taxes',
    ColumnCategory.RATES: 'tw-cat-rates' }


@dataclass( frozen = True )
class HeaderSpan:
    """A top-header cell spanning one group (or, within the income group, one tax-class sub-group): its
    `label`, the category color `css`, and how many columns it `colspan`s."""

    label   : str
    css     : str
    colspan : int


@dataclass( frozen = True )
class HeaderColumn:
    """A column-header cell: its `label` and the category color `css`."""

    label : str
    css   : str


@dataclass( frozen = True )
class WorksheetRow:
    """One tax year: the `year` and its already-formatted cell strings, aligned to the visible columns."""

    year  : int
    cells : tuple[ str, ... ]


@dataclass( frozen = True )
class WorksheetTable:
    """The render model: the group/sub-group header `spans`, the `columns` header row, and the body `rows`.
    Empty (`is_empty`) when nothing survived the all-zero drop -- the page shows a note instead."""

    spans   : tuple[ HeaderSpan, ... ]
    columns : tuple[ HeaderColumn, ... ]
    rows    : tuple[ WorksheetRow, ... ]

    @property
    def is_empty( self ) -> bool:
        return not self.columns


def build_table( worksheet : TaxDisplayWorksheet ) -> WorksheetTable:
    """The render model for `worksheet`, with all-zero columns dropped. Columns keep their group order (and
    income keeps its tax-class sub-group banding); each cell is formatted for its column's units."""
    years   = worksheet.years
    visible = _visible_columns( worksheet, years )
    spans   = tuple( _spans( worksheet, visible ) )
    columns = tuple( HeaderColumn( column.label, _CATEGORY_CSS[ category ] )
                     for category, column in visible )
    rows    = tuple(
        WorksheetRow( row.year,
                      tuple( _format( column.format, row.cells.get( column.key ) )
                             for _category, column in visible ) )
        for row in years )
    return WorksheetTable( spans = spans, columns = columns, rows = rows )


def _visible_columns( worksheet, years ) -> list[ tuple[ ColumnCategory, Column ] ]:
    """Each group's columns that carry a non-zero value in at least one year, paired with their category
    (for coloring), in group then column order."""
    visible = list()
    for group in worksheet.groups:
        for column in group.columns:
            if any( _is_nonzero( row.cells.get( column.key ) ) for row in years ):
                visible.append( ( group.category, column ) )
            continue
        continue
    return visible


def _spans( worksheet, visible ):
    """The top-header spans over the visible columns: one per group, except the income group, which is split
    into a span per contiguous tax-class sub-group (the account's `subgroup`)."""
    visible_keys = { column.key for _category, column in visible }
    for group in worksheet.groups:
        shown = [ column for column in group.columns if column.key in visible_keys ]
        if not shown:
            continue
        css = _CATEGORY_CSS[ group.category ]
        if group.category is ColumnCategory.INCOME:
            for label, run in _subgroup_runs( shown ):
                yield HeaderSpan( label, css, len( run ) )
        else:
            yield HeaderSpan( group.category.label, css, len( shown ) )
        continue


def _subgroup_runs( columns ):
    """Contiguous runs of columns sharing a `subgroup`, as (label, columns) -- the income sub-group bands."""
    runs = list()
    for column in columns:
        label = column.subgroup or ''
        if runs and runs[ -1 ][ 0 ] == label:
            runs[ -1 ][ 1 ].append( column )
        else:
            runs.append( ( label, [ column ] ) )
        continue
    return runs


def _is_nonzero( value : Optional[ Decimal ] ) -> bool:
    return value is not None and value != 0


def _format( column_format : ColumnFormat, value : Optional[ Decimal ] ) -> str:
    """A cell's display string: blank for None (not applicable that year), a percent for a share or rate
    (0.22 -> '22.0%'), else whole dollars with a thousands separator ('-$1,200' for a negative)."""
    if value is None:
        return ''
    if column_format in ( ColumnFormat.PERCENT, ColumnFormat.RATE ):
        return f'{ value * 100 :.1f}%'
    sign = '-' if value < 0 else ''
    return f'{ sign }${ abs( value ):,.0f}'
