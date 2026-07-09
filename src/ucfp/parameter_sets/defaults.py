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
    CatalogScope, EconomicOutlookVariant, ExpenseCategory, ParameterSetKind, PropertyContext )
from .schemas import EconomicOutlookSchedule, ExpenseCatalog, ExpenseType


def _rate( value : str ) -> Rate:
    return Rate( Decimal( value ) )


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


def _expense( name : str, category, amount : str, tax_class, interval = None,
              applies_to : tuple = () ) -> ExpenseType:
    return ExpenseType(
        name = name, category = category, expense_tax_class = tax_class,
        default_amount = Decimal( amount ), interval = interval, applies_to = applies_to )


def _general_expense_catalog() -> ExpenseCatalog:
    """The general expense catalog: the spreadsheet rows restructured into typed, grouped entries, each
    collapsed to a single default amount. Grouping follows the decision each cost attaches to. The
    `PROPERTY` rows are one operating-cost set seeded per owned dwelling; each carries its *personal*
    tax class (materialization swaps it to a rental expense for a rental) and an `applies_to` set of the
    property contexts it seeds against."""
    living         = ExpenseTaxClass.LIVING
    medical        = ExpenseTaxClass.MEDICAL
    salt           = ExpenseTaxClass.SALT
    rental_expense = ExpenseTaxClass.RENTAL_EXPENSE
    weekly     = Duration( 1, TimeUnit.WEEK )
    monthly    = Duration( 1, TimeUnit.MONTH )
    quarterly  = Duration( 3, TimeUnit.MONTH )
    semiannual = Duration( 6, TimeUnit.MONTH )
    yearly     = Duration( 1, TimeUnit.YEAR )
    every_2y   = Duration( 2, TimeUnit.YEAR )
    every_15y  = Duration( 15, TimeUnit.YEAR )
    every_20y  = Duration( 20, TimeUnit.YEAR )
    everyday      = ExpenseCategory.EVERYDAY
    discretionary = ExpenseCategory.DISCRETIONARY
    prop          = ExpenseCategory.PROPERTY
    vehicle       = ExpenseCategory.VEHICLE
    health        = ExpenseCategory.HEALTH
    misc          = ExpenseCategory.MISCELLANEOUS
    # Property-context sets: every owned dwelling; owned dwellings plus a tenant's rented home
    # (utilities); an owned rental alone (property management).
    owned       = ( PropertyContext.RESIDENCE, PropertyContext.SECOND_HOME, PropertyContext.RENTAL )
    occupied    = owned + ( PropertyContext.RENTED_HOME, )
    rental_only = ( PropertyContext.RENTAL, )
    rented_only = ( PropertyContext.RENTED_HOME, )
    return ExpenseCatalog( [
        # Everyday living
        _expense( 'Food', everyday, '150', living, weekly ),
        _expense( 'Consumables', everyday, '50', living, weekly ),
        _expense( 'Clothes', everyday, '1250', living ),
        _expense( 'Grooming', everyday, '960', living ),
        # Discretionary
        _expense( 'Vacations', discretionary, '10000', living ),
        _expense( 'Transportation / Travel', discretionary, '900', living, quarterly ),
        _expense( 'Dining Out', discretionary, '75', living, weekly ),
        _expense( 'Entertainment', discretionary, '50', living, weekly ),
        _expense( 'Cable TV / Streaming', discretionary, '100', living, monthly ),
        _expense( 'Hobbies', discretionary, '150', living, quarterly ),
        _expense( 'Computer Purchase', discretionary, '1500', living, every_2y ),
        _expense( 'Computer Services', discretionary, '300', living ),
        _expense( 'Gifts', discretionary, '3000', living ),
        _expense( 'Health & Fitness', discretionary, '40', living, monthly ),
        _expense( 'Furniture', discretionary, '500', living ),
        # Property -- one operating-cost set per owned dwelling. Tax class is the PERSONAL class
        # (property tax -> SALT, the rest -> living); materialization swaps it to a rental expense for
        # a rental. Utilities also seed a tenant's rented home; rent and property management apply to a
        # single context only -- the rented home and an owned rental respectively.
        _expense( 'Rent', prop, '1500', living, monthly, applies_to = rented_only ),
        _expense( 'Property Tax', prop, '6000', salt, yearly, applies_to = owned ),
        _expense( 'Property Insurance', prop, '2500', living, applies_to = owned ),
        _expense( 'HOA / Coop Fee', prop, '300', living, monthly, applies_to = owned ),
        _expense( 'Maintenance / Repair', prop, '200', living, monthly, applies_to = owned ),
        _expense( 'A/C Cost', prop, '9000', living, every_15y, applies_to = owned ),
        _expense( 'Appliance', prop, '580', living, applies_to = owned ),
        _expense( 'Pest Control', prop, '110', living, quarterly, applies_to = owned ),
        _expense( 'Roof Cost', prop, '15000', living, every_20y, applies_to = owned ),
        _expense( 'Pool Maintenance', prop, '125', living, monthly, applies_to = owned ),
        _expense( 'Lawn Maintenance', prop, '125', living, monthly, applies_to = owned ),
        _expense( 'Lawn Tools', prop, '100', living, applies_to = owned ),
        _expense( 'Water / Wastewater', prop, '200', living, monthly, applies_to = occupied ),
        _expense( 'Electric', prop, '250', living, monthly, applies_to = occupied ),
        _expense( 'Gas Utility', prop, '80', living, monthly, applies_to = occupied ),
        _expense( 'Phone Service', prop, '100', living, monthly, applies_to = occupied ),
        _expense( 'Internet', prop, '100', living, monthly, applies_to = occupied ),
        _expense( 'Property Management', prop, '240', rental_expense, monthly, applies_to = rental_only ),
        # Vehicle running costs (the car purchase/financing itself is the parameterized vehicle plan,
        # not a catalog item)
        _expense( 'Auto Insurance', vehicle, '750', living, semiannual ),
        _expense( 'Auto Maintenance', vehicle, '300', living, yearly ),
        _expense( 'Auto Repair', vehicle, '1000', living ),
        _expense( 'Gasoline', vehicle, '20', living, weekly ),
        # Health
        _expense( 'Medical Expenses', health, '7200', medical ),
        _expense( 'Health Insurance', health, '26400', medical ),
        # Miscellaneous -- household costs not tied to a single dwelling
        _expense( 'Umbrella Insurance', misc, '500', living ),
        _expense( 'Professional Fees', misc, '500', living, yearly ),
    ] )


def canonical_defaults() -> dict:
    """All seed presets, keyed by kind then by the variant/scope whose `label` names the set."""
    return {
        ParameterSetKind.ECONOMIC_OUTLOOK: _economic_outlook_presets(),
        ParameterSetKind.EXPENSE_CATALOG: { CatalogScope.GENERAL: _general_expense_catalog() },
    }
