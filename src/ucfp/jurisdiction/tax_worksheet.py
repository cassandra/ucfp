"""The tax display worksheet: a jurisdiction's year-by-year tax calculation, shaped as a table for display.

The forecast books hold the final per-layer taxes but none of the worksheet *inputs* -- the AGI, provisional
income, deductions, marginal/effective rates, and bracket headroom a tax planner wants to see. This module
is the neutral, jurisdiction-agnostic shape those figures are captured in: ordered column groups, the
columns within them (which a jurisdiction's tax engine defines), and one value row per tax year. The
renderer draws whatever schema it is handed, so it never needs to know the jurisdiction; only the producing
engine knows which columns it emits.

The name stresses the role -- a *display* artifact -- to set it apart from the engine's `TaxFigures`, which
carries derived figures back into the tax computation (NIIT, IRMAA) rather than to the screen.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from common.labeled_enum import LabeledEnum

from ucfp.jurisdiction.enums import JurisdictionType


class ColumnCategory( LabeledEnum ):
    """The worksheet's four column groups, in render order. The label is the group heading; a stylesheet
    keys the group's color off the member name. The categories are shared across jurisdictions -- general
    enough to color and order consistently -- while the columns within each group are jurisdiction-specific."""

    INCOME         = ( 'Income Accounts', 'The taxable income accounts feeding the return.' )
    INCOME_DERIVED = ( 'Income Calculations', 'Figures derived from income on the way to the tax.' )
    TAXES          = ( 'Tax Values', 'The taxes assessed for the year.' )
    RATES          = ( 'Tax Rates', 'Marginal and effective rates, and bracket headroom.' )


class ColumnFormat( Enum ):
    """How a cell's Decimal renders: a dollar amount, a percentage, or a tax rate (both shown as percents,
    kept distinct so the renderer -- or a later refinement -- can treat a rate differently from a share)."""

    MONEY   = 'money'
    PERCENT = 'percent'
    RATE    = 'rate'


@dataclass( frozen = True )
class Column:
    """One worksheet column: its stable `key` (how each year's cells address it), the display `label`, the
    `format` its values render in, and an optional `subgroup` -- a single level of secondary grouping within
    a column group. The income columns set it to band leaf accounts by tax class; the renderer draws a
    spanning sub-header over each run of contiguous columns that share a subgroup."""

    key      : str
    label    : str
    format   : ColumnFormat
    subgroup : Optional[ str ] = None


@dataclass( frozen = True )
class ColumnGroup:
    """One of the worksheet's four category groups with its ordered `columns`."""

    category : ColumnCategory
    columns  : tuple[ Column, ... ]


@dataclass( frozen = True )
class YearRow:
    """One tax year's values, each addressed by its column `key`. A key that is absent or maps to None is
    'not applicable that year'; a present value is in its column's units -- dollars for MONEY, a fraction
    for PERCENT/RATE (0.22 renders as 22%)."""

    year  : int
    cells : dict[ str, Optional[ Decimal ] ]


@dataclass( frozen = True )
class TaxDisplayWorksheet:
    """A jurisdiction's year-by-year tax worksheet for display. `groups` is the ordered column schema (which
    columns exist, their labels, formats, and grouping); `years` is one `YearRow` per tax year. The schema
    travels with the worksheet, so a captured run always renders the columns it was computed with, even if
    the producing layout later changes. An engine builds one single-year worksheet per assessment; the run
    assembles those into one worksheet sharing the schema (see the planning orchestration)."""

    jurisdiction : JurisdictionType
    groups       : tuple[ ColumnGroup, ... ]
    years        : tuple[ YearRow, ... ]
