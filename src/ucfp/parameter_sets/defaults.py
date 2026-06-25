"""The canonical seed values for the parameter-set library -- the source of truth the seed
command writes into the database, and the values an untouched system default stays current with.

Defined in code so they ship and update with the app; materialized to the database by
`seed_parameter_sets` and read from the database at runtime (never from here directly). Each
economic outlook is a single unbounded segment for now -- the schedule shape is in place, so
pinning rates to year ranges is just more segments later.
"""
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import ExpenseTaxClass
from ucfp.forecast.economic_outlook import EconomicParameters

from .enums import (
    CatalogScope, EconomicOutlookVariant, ExpenseCategory, LifestyleScope, ParameterSetKind )
from .schemas import (
    EconomicOutlookSchedule, ExpenseCatalog, ExpenseType, LifestyleAmounts, LifestyleCostTable,
    LifestyleExpense )


def _rate( value : str ) -> Rate:
    return Rate( Decimal( value ) )


def _amounts( low : str, medium : str, high : str ) -> LifestyleAmounts:
    return LifestyleAmounts( Decimal( low ), Decimal( medium ), Decimal( high ) )


def _economic_outlook_presets() -> dict:
    return {
        EconomicOutlookVariant.OPTIMISTIC: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                = _rate( '0.02' ),
            medical_inflation        = _rate( '0.04' ),
            wage_growth              = _rate( '0.035' ),
            savings_interest         = _rate( '0.025' ),
            cd_interest              = _rate( '0.035' ),
            bond_interest            = _rate( '0.045' ),
            stock_appreciation       = _rate( '0.075' ),
            stock_dividend           = _rate( '0.02' ),
            real_estate_appreciation = _rate( '0.045' ),
            retirement_growth        = _rate( '0.07' ),
            social_security_cola     = _rate( '0.025' ),
            pension_cola             = _rate( '0.025' ),
            rental_increase          = _rate( '0.035' ),
        ) ] ),
        EconomicOutlookVariant.EXPECTED: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                = _rate( '0.025' ),
            medical_inflation        = _rate( '0.045' ),
            wage_growth              = _rate( '0.03' ),
            savings_interest         = _rate( '0.02' ),
            cd_interest              = _rate( '0.03' ),
            bond_interest            = _rate( '0.04' ),
            stock_appreciation       = _rate( '0.06' ),
            stock_dividend           = _rate( '0.018' ),
            real_estate_appreciation = _rate( '0.035' ),
            retirement_growth        = _rate( '0.055' ),
            social_security_cola     = _rate( '0.025' ),
            pension_cola             = _rate( '0.02' ),
            rental_increase          = _rate( '0.03' ),
        ) ] ),
        EconomicOutlookVariant.PESSIMISTIC: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                = _rate( '0.03' ),
            medical_inflation        = _rate( '0.05' ),
            wage_growth              = _rate( '0.025' ),
            savings_interest         = _rate( '0.015' ),
            cd_interest              = _rate( '0.025' ),
            bond_interest            = _rate( '0.035' ),
            stock_appreciation       = _rate( '0.045' ),
            stock_dividend           = _rate( '0.018' ),
            real_estate_appreciation = _rate( '0.025' ),
            retirement_growth        = _rate( '0.04' ),
            social_security_cola     = _rate( '0.02' ),
            pension_cola             = _rate( '0.0' ),
            rental_increase          = _rate( '0.025' ),
        ) ] ),
    }


def _general_lifestyle_table() -> LifestyleCostTable:
    """The general (non-regional) lifestyle cost table, in spreadsheet order. An item carries an
    `interval` and per-occurrence values (the engine places it); a stream omits the interval and
    its values are annual (the spreadsheet's occurrences-per-year folded in -- e.g. a 2x-monthly
    cost as 24 x its base). Tax class is LIVING except medical care and health insurance
    (MEDICAL). Multiplier rows: Medical / Health Insurance / Grooming (xN per month) and Appliance
    (7 over 12 years) become annual streams; Computer Purchase (2 every 4 years) is one item every
    two years.
    """
    living      = ExpenseTaxClass.LIVING
    medical     = ExpenseTaxClass.MEDICAL
    weekly      = Duration( 1, TimeUnit.WEEK )
    monthly     = Duration( 1, TimeUnit.MONTH )
    quarterly   = Duration( 3, TimeUnit.MONTH )
    semiannual  = Duration( 6, TimeUnit.MONTH )
    yearly      = Duration( 1, TimeUnit.YEAR )
    every_2y    = Duration( 2, TimeUnit.YEAR )
    every_10y   = Duration( 10, TimeUnit.YEAR )
    every_15y   = Duration( 15, TimeUnit.YEAR )
    every_20y   = Duration( 20, TimeUnit.YEAR )
    return LifestyleCostTable( [
        LifestyleExpense( 'Automobile Purchase',
                          _amounts( '15000', '25000', '35000' ), living, every_10y ),
        LifestyleExpense( 'Auto Insurance', _amounts( '500', '750', '1000' ), living, semiannual ),
        LifestyleExpense( 'Auto Maintenance', _amounts( '200', '300', '500' ), living, yearly ),
        LifestyleExpense( 'Auto Repair', _amounts( '1000', '1000', '1000' ), living ),
        LifestyleExpense( 'Gas', _amounts( '10', '20', '50' ), living, weekly ),
        LifestyleExpense( 'Home Insurance', _amounts( '2500', '2500', '2500' ), living ),
        LifestyleExpense( 'House Maintenance / Repair',
                          _amounts( '200', '200', '200' ), living, monthly ),
        LifestyleExpense( 'A/C Cost', _amounts( '8000', '9000', '10000' ), living, every_15y ),
        LifestyleExpense( 'Appliance', _amounts( '580', '580', '696' ), living ),
        LifestyleExpense( 'Pest Control', _amounts( '110', '110', '110' ), living, quarterly ),
        LifestyleExpense( 'Roof Cost', _amounts( '15000', '15000', '15000' ), living, every_20y ),
        LifestyleExpense( 'Pool Maintenance', _amounts( '125', '125', '125' ), living, monthly ),
        LifestyleExpense( 'Lawn Maintenance', _amounts( '125', '125', '125' ), living, monthly ),
        LifestyleExpense( 'Lawn Tools', _amounts( '50', '100', '200' ), living ),
        LifestyleExpense( 'Furniture', _amounts( '250', '500', '750' ), living ),
        LifestyleExpense( 'Water / Wastewater', _amounts( '200', '200', '200' ), living, monthly ),
        LifestyleExpense( 'Electric', _amounts( '250', '250', '250' ), living, monthly ),
        LifestyleExpense( 'Phone Service', _amounts( '100', '100', '100' ), living, monthly ),
        LifestyleExpense( 'Internet', _amounts( '100', '100', '100' ), living, monthly ),
        LifestyleExpense( 'Food', _amounts( '100', '150', '200' ), living, weekly ),
        LifestyleExpense( 'Consumables', _amounts( '50', '50', '50' ), living, weekly ),
        LifestyleExpense( 'Clothes', _amounts( '1000', '1250', '2000' ), living ),
        LifestyleExpense( 'Medical Expenses', _amounts( '12000', '7200', '4800' ), medical ),
        LifestyleExpense( 'Health Insurance', _amounts( '21600', '26400', '30000' ), medical ),
        LifestyleExpense( 'Umbrella Insurance', _amounts( '0', '500', '800' ), living ),
        LifestyleExpense( 'Major Vacation', _amounts( '5000', '7500', '15000' ), living ),
        LifestyleExpense( 'Minor Vacation', _amounts( '2000', '3000', '7500' ), living ),
        LifestyleExpense( 'Travel', _amounts( '600', '900', '1200' ), living, quarterly ),
        LifestyleExpense( 'Grooming', _amounts( '720', '960', '1200' ), living ),
        LifestyleExpense( 'Health & Fitness', _amounts( '30', '40', '50' ), living, monthly ),
        LifestyleExpense( 'Computer Purchase',
                          _amounts( '1000', '1500', '2000' ), living, every_2y ),
        LifestyleExpense( 'Computer Services', _amounts( '200', '300', '400' ), living ),
        LifestyleExpense( 'Entertainment', _amounts( '25', '50', '100' ), living, weekly ),
        LifestyleExpense( 'Hobbies', _amounts( '100', '150', '200' ), living, quarterly ),
        LifestyleExpense( 'Gifts', _amounts( '1000', '3000', '8000' ), living ),
    ] )


def _expense( name : str, category, amount : str, tax_class, interval = None,
              flex : bool = False ) -> ExpenseType:
    return ExpenseType(
        name = name, category = category, expense_tax_class = tax_class,
        default_amount = Decimal( amount ), interval = interval, lifestyle_dependent = flex )


def _general_expense_catalog() -> ExpenseCatalog:
    """The general expense catalog: the 35 spreadsheet rows restructured into typed, grouped
    entries, each collapsed to its medium value as the default and flagged lifestyle-dependent where
    the original tiers differed. Grouping follows the decision each cost attaches to; only the
    genuinely discretionary rows flex. Property tax, charitable giving, and the rental-context
    variants are added with the sections that introduce their context."""
    living  = ExpenseTaxClass.LIVING
    medical = ExpenseTaxClass.MEDICAL
    weekly     = Duration( 1, TimeUnit.WEEK )
    monthly    = Duration( 1, TimeUnit.MONTH )
    quarterly  = Duration( 3, TimeUnit.MONTH )
    semiannual = Duration( 6, TimeUnit.MONTH )
    yearly     = Duration( 1, TimeUnit.YEAR )
    every_2y   = Duration( 2, TimeUnit.YEAR )
    every_10y  = Duration( 10, TimeUnit.YEAR )
    every_15y  = Duration( 15, TimeUnit.YEAR )
    every_20y  = Duration( 20, TimeUnit.YEAR )
    everyday      = ExpenseCategory.EVERYDAY
    discretionary = ExpenseCategory.DISCRETIONARY
    utilities     = ExpenseCategory.UTILITIES
    home          = ExpenseCategory.HOME
    auto          = ExpenseCategory.AUTO
    health        = ExpenseCategory.HEALTH
    return ExpenseCatalog( [
        # Everyday living
        _expense( 'Food', everyday, '150', living, weekly, flex = True ),
        _expense( 'Consumables', everyday, '50', living, weekly ),
        _expense( 'Clothes', everyday, '1250', living, flex = True ),
        _expense( 'Grooming', everyday, '960', living, flex = True ),
        # Discretionary
        _expense( 'Major Vacation', discretionary, '7500', living, flex = True ),
        _expense( 'Minor Vacation', discretionary, '3000', living, flex = True ),
        _expense( 'Travel', discretionary, '900', living, quarterly, flex = True ),
        _expense( 'Entertainment', discretionary, '50', living, weekly, flex = True ),
        _expense( 'Hobbies', discretionary, '150', living, quarterly, flex = True ),
        _expense( 'Computer Purchase', discretionary, '1500', living, every_2y, flex = True ),
        _expense( 'Computer Services', discretionary, '300', living, flex = True ),
        _expense( 'Gifts', discretionary, '3000', living, flex = True ),
        _expense( 'Health & Fitness', discretionary, '40', living, monthly, flex = True ),
        _expense( 'Furniture', discretionary, '500', living, flex = True ),
        # Utilities
        _expense( 'Water / Wastewater', utilities, '200', living, monthly ),
        _expense( 'Electric', utilities, '250', living, monthly ),
        _expense( 'Phone Service', utilities, '100', living, monthly ),
        _expense( 'Internet', utilities, '100', living, monthly ),
        # Home
        _expense( 'Home Insurance', home, '2500', living ),
        _expense( 'House Maintenance / Repair', home, '200', living, monthly ),
        _expense( 'A/C Cost', home, '9000', living, every_15y, flex = True ),
        _expense( 'Appliance', home, '580', living, flex = True ),
        _expense( 'Pest Control', home, '110', living, quarterly ),
        _expense( 'Roof Cost', home, '15000', living, every_20y ),
        _expense( 'Pool Maintenance', home, '125', living, monthly ),
        _expense( 'Lawn Maintenance', home, '125', living, monthly ),
        _expense( 'Lawn Tools', home, '100', living, flex = True ),
        _expense( 'Umbrella Insurance', home, '500', living, flex = True ),
        # Auto
        _expense( 'Automobile Purchase', auto, '25000', living, every_10y, flex = True ),
        _expense( 'Auto Insurance', auto, '750', living, semiannual, flex = True ),
        _expense( 'Auto Maintenance', auto, '300', living, yearly, flex = True ),
        _expense( 'Auto Repair', auto, '1000', living ),
        _expense( 'Gas', auto, '20', living, weekly, flex = True ),
        # Health
        _expense( 'Medical Expenses', health, '7200', medical, flex = True ),
        _expense( 'Health Insurance', health, '26400', medical, flex = True ),
    ] )


def canonical_defaults() -> dict:
    """All seed presets, keyed by kind then by the variant/scope whose `label` names the set."""
    return {
        ParameterSetKind.ECONOMIC_OUTLOOK: _economic_outlook_presets(),
        ParameterSetKind.LIFESTYLE_COSTS: { LifestyleScope.GENERAL: _general_lifestyle_table() },
        ParameterSetKind.EXPENSE_CATALOG: { CatalogScope.GENERAL: _general_expense_catalog() },
    }
