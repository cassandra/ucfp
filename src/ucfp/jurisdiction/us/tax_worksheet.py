"""Builds the US federal tax display worksheet for one tax year from the figures a tax assessment produces.

The neutral `TaxDisplayWorksheet` shape carries labeled columns and a per-year value row; this module owns
the US layout -- which columns exist, their labels, formats, and order -- and the worksheet-only derivations
the tax computation itself does not need: the taxable-Social-Security share, the marginal and effective
rates, and the bracket headroom a planner reads. The engine gathers the intermediates it already has into
`TaxYearInputs` and calls `build_worksheet`, so the assessment stays focused on the tax while the
presentation lives here, isolated and testable.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ucfp.accounts.books import Account
from ucfp.accounts.enums import IncomeTaxClass
from ucfp.jurisdiction.brackets import BracketTable
from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.tax_worksheet import (
    Column, ColumnCategory, ColumnFormat, ColumnGroup, TaxDisplayWorksheet, YearRow )

_ZERO = Decimal( '0' )

# The income tax classes shown in the Income group, in display order (earned, then ordinary, then interest
# and dividends, then the preferential gains, then Social Security and tax-exempt interest). Each account's
# class is its sub-group heading; a revenue account whose class is absent here -- TAX_FREE, excluded from tax
# everywhere -- is left off the worksheet.
_INCOME_CLASS_ORDER = (
    IncomeTaxClass.WAGES,
    IncomeTaxClass.ORDINARY,
    IncomeTaxClass.PENSION,
    IncomeTaxClass.RETIREMENT_DISTRIBUTION,
    IncomeTaxClass.GROSS_RENTAL,
    IncomeTaxClass.ROTH_EARNINGS,
    IncomeTaxClass.SHORT_TERM_GAINS,
    IncomeTaxClass.TAXABLE_INTEREST,
    IncomeTaxClass.QUALIFIED_DIVIDENDS,
    IncomeTaxClass.LONG_TERM_GAINS,
    IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
    IncomeTaxClass.SECOND_HOME_GAIN,
    IncomeTaxClass.RENTAL_SALE_GAIN,
    IncomeTaxClass.SECTION_1250_GAIN,
    IncomeTaxClass.COLLECTIBLES_GAINS,
    IncomeTaxClass.SOCIAL_SECURITY,
    IncomeTaxClass.TAX_EXEMPT_INTEREST )

_INCOME_CLASS_RANK = { tax_class: rank for rank, tax_class in enumerate( _INCOME_CLASS_ORDER ) }


@dataclass( frozen = True )
class TaxYearInputs:
    """The one-year figures the worksheet is built from -- the intermediates a US federal assessment already
    computes (surfaced here rather than discarded), plus the year's bracket tables and NIIT threshold the
    marginal-rate and headroom columns need. `income_accounts` is every revenue account with its year total,
    for the per-account Income columns."""

    year                    : int
    ordinary_brackets       : BracketTable
    ltcg_brackets           : BracketTable
    niit_threshold          : Decimal
    income_accounts         : list[ tuple[ Account, Decimal ] ]
    provisional_income      : Decimal
    ss_gross                : Decimal
    taxable_ss              : Decimal
    agi                     : Decimal
    taxable_long_term_gains : Decimal
    net_investment_income   : Decimal
    standard_deduction      : Decimal
    taxable_ordinary_income : Decimal
    applied_deduction       : Decimal
    taxable_income          : Decimal
    niit_magi               : Decimal
    ordinary_tax            : Decimal
    capital_gains_tax       : Decimal
    section_1250_tax        : Decimal
    collectibles_tax        : Decimal
    niit                    : Decimal
    state_income_tax        : Decimal
    total_tax               : Decimal


# The fixed (non-income) columns, in display order per group: (key, label, format).
_DERIVED_COLUMNS = (
    ( 'provisional_income', 'Provisional Income', ColumnFormat.MONEY ),
    ( 'taxable_ss_pct', 'Taxable Social Security %', ColumnFormat.PERCENT ),
    ( 'agi', 'Adjusted Gross Income (AGI)', ColumnFormat.MONEY ),
    ( 'taxable_ltcg', 'Taxable Long-Term Gains', ColumnFormat.MONEY ),
    ( 'net_investment_income', 'Net Investment Income', ColumnFormat.MONEY ),
    ( 'standard_deduction', 'Standard Deduction', ColumnFormat.MONEY ),
    ( 'applied_deduction', 'Applied Deduction', ColumnFormat.MONEY ),
    ( 'taxable_ordinary', 'Taxable Ordinary Income', ColumnFormat.MONEY ) )

_TAX_COLUMNS = (
    ( 'ordinary_tax', 'Ordinary Income Tax', ColumnFormat.MONEY ),
    ( 'capital_gains_tax', 'Long-Term Capital Gains', ColumnFormat.MONEY ),
    ( 'section_1250_tax', 'Section 1250 Recapture', ColumnFormat.MONEY ),
    ( 'collectibles_tax', 'Collectibles Tax', ColumnFormat.MONEY ),
    ( 'niit', 'Net Investment Income Tax', ColumnFormat.MONEY ),
    ( 'state_income_tax', 'State Income Tax', ColumnFormat.MONEY ),
    ( 'total_tax', 'Total Tax', ColumnFormat.MONEY ) )

_RATE_COLUMNS = (
    ( 'marginal_ordinary', 'Marginal (ordinary)', ColumnFormat.RATE ),
    ( 'marginal_cap_gains', 'Marginal (capital gains)', ColumnFormat.RATE ),
    ( 'effective', 'Effective (overall)', ColumnFormat.RATE ),
    ( 'headroom_ordinary', 'Headroom (ordinary)', ColumnFormat.MONEY ),
    ( 'headroom_ltcg', 'Headroom (LTCG)', ColumnFormat.MONEY ),
    # Not a bracket headroom like the two above: the distance from AGI (the model's NIIT MAGI) to the NIIT
    # threshold -- how much more income before the 3.8% tax begins applying to net investment income.
    ( 'headroom_niit', 'AGI to NIIT threshold', ColumnFormat.MONEY ) )


def build_worksheet( inputs : TaxYearInputs ) -> TaxDisplayWorksheet:
    """The one-year US federal tax display worksheet for `inputs`: the four column groups (income accounts,
    income calculations, tax values, tax rates) and a single value row. The run assembles per-year
    worksheets into one sharing this schema."""
    income_columns, income_cells = _income_group( inputs.income_accounts )
    groups = (
        ColumnGroup( ColumnCategory.INCOME, income_columns ),
        ColumnGroup( ColumnCategory.INCOME_DERIVED, _columns( _DERIVED_COLUMNS ) ),
        ColumnGroup( ColumnCategory.TAXES, _columns( _TAX_COLUMNS ) ),
        ColumnGroup( ColumnCategory.RATES, _columns( _RATE_COLUMNS ) ) )
    cells = { ** income_cells, ** _derived_cells( inputs ), ** _tax_cells( inputs ),
              ** _rate_cells( inputs ) }
    return TaxDisplayWorksheet(
        jurisdiction = JurisdictionType.US_FEDERAL,
        groups       = groups,
        years        = ( YearRow( year = inputs.year, cells = cells ), ) )


def _columns( specs ) -> tuple[ Column, ... ]:
    return tuple( Column( key = key, label = label, format = fmt ) for key, label, fmt in specs )


def _income_group(
        income_accounts : list[ tuple[ Account, Decimal ] ] ) -> tuple[ tuple[ Column, ... ], dict ]:
    """The Income columns and their cells: one column per taxable revenue account, ordered by tax class then
    the account's chart order, each banded (as a sub-group) by its tax class. TAX_FREE accounts are left
    off. The column key is the account handle, so the schema is stable across the run's years."""
    shown = [ ( account, amount ) for account, amount in income_accounts
              if account.income_tax_class in _INCOME_CLASS_RANK ]
    ordered = sorted( enumerate( shown ),
                      key = lambda item: ( _INCOME_CLASS_RANK[ item[ 1 ][ 0 ].income_tax_class ], item[ 0 ] ) )
    columns = list()
    cells   = dict()
    for _position, ( account, amount ) in ordered:
        # Key on the account's stable UUID, not its handle: revenue accounts carry no handle, so keying on
        # `handle` collapses every income column onto one shared `None` key. `account_uuid` is the per-account
        # identity meant for exactly this (a results-table column) and is stable across the run's years.
        key = f'income:{ account.account_uuid }'
        columns.append( Column(
            key = key, label = account.name, format = ColumnFormat.MONEY,
            subgroup = account.income_tax_class.label ) )
        cells[ key ] = amount
        continue
    return tuple( columns ), cells


def _derived_cells( inputs : TaxYearInputs ) -> dict:
    return {
        'provisional_income'    : inputs.provisional_income,
        'taxable_ss_pct'        : _ratio( inputs.taxable_ss, inputs.ss_gross ),
        'agi'                   : inputs.agi,
        'taxable_ltcg'          : inputs.taxable_long_term_gains,
        'net_investment_income' : inputs.net_investment_income,
        'standard_deduction'    : inputs.standard_deduction,
        'applied_deduction'     : inputs.applied_deduction,
        'taxable_ordinary'      : inputs.taxable_ordinary_income }


def _tax_cells( inputs : TaxYearInputs ) -> dict:
    return {
        'ordinary_tax'     : inputs.ordinary_tax,
        'capital_gains_tax' : inputs.capital_gains_tax,
        'section_1250_tax' : inputs.section_1250_tax,
        'collectibles_tax' : inputs.collectibles_tax,
        'niit'             : inputs.niit,
        'state_income_tax' : inputs.state_income_tax,
        'total_tax'        : inputs.total_tax }


def _rate_cells( inputs : TaxYearInputs ) -> dict:
    # Long-term gains stack on top of taxable ordinary income, so the marginal gains rate and its headroom
    # are read at that stacked position in the preferential-rate table.
    gains_position = inputs.taxable_ordinary_income + inputs.taxable_long_term_gains
    return {
        'marginal_ordinary'  : inputs.ordinary_brackets.marginal_rate( inputs.taxable_ordinary_income ),
        'marginal_cap_gains' : inputs.ltcg_brackets.marginal_rate( gains_position ),
        'effective'          : _ratio( inputs.total_tax, inputs.taxable_income ),
        'headroom_ordinary'  : _headroom( inputs.ordinary_brackets, inputs.taxable_ordinary_income ),
        'headroom_ltcg'      : _headroom( inputs.ltcg_brackets, gains_position ),
        'headroom_niit'      : max( _ZERO, inputs.niit_threshold - inputs.niit_magi ) }


def _ratio( numerator : Decimal, denominator : Decimal ) -> Optional[ Decimal ]:
    """`numerator / denominator` as a fraction (0.22 for 22%), or None when the denominator is zero -- a
    rate or share with no base is not applicable that year rather than a divide-by-zero."""
    if denominator == 0:
        return None
    return numerator / denominator


def _headroom( brackets : BracketTable, amount : Decimal ) -> Optional[ Decimal ]:
    """The room left before `amount` crosses into the next bracket, or None in the top bracket (no ceiling
    -- unbounded headroom)."""
    ceiling = brackets.ceiling( amount )
    if ceiling is None:
        return None
    return ceiling - amount
