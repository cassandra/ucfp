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
    CadenceDomain, CatalogScope, EconomicOutlookVariant, ExpenseCategory, ParameterSetKind,
    PropertyContext, Realization )
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


def _expense( name : str, category, amount : str, tax_class, interval, realization, domain,
              applies_to : tuple = () ) -> ExpenseType:
    return ExpenseType(
        name = name, category = category, expense_tax_class = tax_class,
        default_amount = Decimal( amount ), interval = interval, realization = realization,
        cadence_domain = domain, applies_to = applies_to )


def _durable( name : str, category, count : int, cost_each : str, lifespan : int, tax_class,
              applies_to : tuple = () ) -> ExpenseType:
    """A durable-replacement expense entered as `count` items at `cost_each`, replaced every `lifespan`
    years. Its amount is the annualized cost (count x cost_each / lifespan) -- a calculator fills it --
    so it materializes as a smoothed yearly stream (staggered replacements average out); the cadence is
    a fixed yearly, the replacement lifespan being a calculator input, not the expense's interval."""
    cost   = Decimal( cost_each )
    annual = count * cost / lifespan
    return ExpenseType(
        name = name, category = category, expense_tax_class = tax_class,
        default_amount = annual, interval = Duration( 1, TimeUnit.YEAR ), realization = Realization.SMOOTH,
        cadence_domain = CadenceDomain.FIXED, applies_to = applies_to,
        count = count, cost_each = cost, lifespan = lifespan )


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
    every_15y  = Duration( 15, TimeUnit.YEAR )
    every_20y  = Duration( 20, TimeUnit.YEAR )
    everyday      = ExpenseCategory.EVERYDAY
    discretionary = ExpenseCategory.DISCRETIONARY
    prop          = ExpenseCategory.PROPERTY
    vehicle       = ExpenseCategory.VEHICLE
    health        = ExpenseCategory.HEALTH
    misc          = ExpenseCategory.MISCELLANEOUS
    # Realization (fixed): SMOOTH annualizes and spreads a cost; DISCRETE places it at its cadence.
    smooth   = Realization.SMOOTH
    discrete = Realization.DISCRETE
    # Cadence input domains (which cadences the user may re-select): a fixed cadence, weekly<->monthly,
    # monthly<->yearly, or every N years.
    fixed    = CadenceDomain.FIXED
    wk_mo    = CadenceDomain.WK_MO
    mo_yr    = CadenceDomain.MO_YR
    n_years  = CadenceDomain.N_YEARS
    # Property-context sets: every owned dwelling; owned dwellings plus a tenant's rented home
    # (utilities); an owned rental alone (property management).
    owned       = ( PropertyContext.RESIDENCE, PropertyContext.SECOND_HOME, PropertyContext.RENTAL )
    occupied    = owned + ( PropertyContext.RENTED_HOME, )
    rental_only = ( PropertyContext.RENTAL, )
    rented_only = ( PropertyContext.RENTED_HOME, )
    return ExpenseCatalog( [
        # Everyday living -- continuous consumption, smoothed; entered weekly or monthly.
        _expense( 'Food', everyday, '150', living, weekly, smooth, wk_mo ),
        _expense( 'Consumables', everyday, '50', living, weekly, smooth, wk_mo ),
        _expense( 'Clothes', everyday, '1250', living, yearly, smooth, mo_yr ),
        _expense( 'Grooming', everyday, '960', living, yearly, smooth, mo_yr ),
        # Discretionary -- a mix: smoothed budgets, subscriptions (fixed monthly), and discrete events.
        _expense( 'Vacations', discretionary, '10000', living, yearly, discrete, mo_yr ),
        _expense( 'Transportation / Travel', discretionary, '900', living, quarterly, smooth, mo_yr ),
        _expense( 'Dining Out', discretionary, '75', living, weekly, smooth, wk_mo ),
        _expense( 'Entertainment', discretionary, '50', living, weekly, smooth, wk_mo ),
        _expense( 'Cable TV / Streaming', discretionary, '100', living, monthly, discrete, fixed ),
        _expense( 'Hobbies', discretionary, '150', living, quarterly, smooth, mo_yr ),
        _durable( 'Computer Purchase', discretionary, 2, '1500', 4, living ),
        _expense( 'Computer Services', discretionary, '300', living, yearly, smooth, mo_yr ),
        _expense( 'Gifts', discretionary, '3000', living, yearly, smooth, mo_yr ),
        _expense( 'Health & Fitness', discretionary, '40', living, monthly, discrete, fixed ),
        _expense( 'Furniture', discretionary, '500', living, yearly, smooth, mo_yr ),
        # Property -- one operating-cost set per owned dwelling. Tax class is the PERSONAL class
        # (property tax -> SALT, the rest -> living); materialization swaps it to a rental expense for
        # a rental. Utilities also seed a tenant's rented home; rent and property management apply to a
        # single context only -- the rented home and an owned rental respectively. Utilities/services are
        # a fixed cadence; tax/insurance let the user choose monthly (escrow) or yearly.
        _expense( 'Rent', prop, '1500', living, monthly, discrete, fixed, applies_to = rented_only ),
        _expense( 'Property Tax', prop, '6000', salt, yearly, discrete, mo_yr, applies_to = owned ),
        _expense( 'Property Insurance', prop, '2500', living, yearly, discrete, mo_yr, applies_to = owned ),
        _expense( 'HOA / Coop Fee', prop, '300', living, monthly, discrete, fixed, applies_to = owned ),
        _expense( 'Maintenance / Repair', prop, '200', living, monthly, smooth, mo_yr, applies_to = owned ),
        _expense( 'A/C Cost', prop, '9000', living, every_15y, discrete, n_years, applies_to = owned ),
        _durable( 'Appliance', prop, 3, '2900', 15, living, applies_to = owned ),
        _expense( 'Pest Control', prop, '110', living, quarterly, discrete, fixed, applies_to = owned ),
        _expense( 'Roof Cost', prop, '15000', living, every_20y, discrete, n_years, applies_to = owned ),
        _expense( 'Pool Maintenance', prop, '125', living, monthly, discrete, fixed, applies_to = owned ),
        _expense( 'Lawn Maintenance', prop, '125', living, monthly, discrete, fixed, applies_to = owned ),
        _durable( 'Lawn Tools', prop, 4, '500', 20, living, applies_to = owned ),
        _expense( 'Water / Wastewater', prop, '200', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Electric', prop, '250', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Gas Utility', prop, '80', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Phone Service', prop, '100', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Internet', prop, '100', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Property Management', prop, '240', rental_expense, monthly, discrete, fixed, applies_to = rental_only ),
        # Vehicle running costs (the car purchase/financing itself is the parameterized vehicle plan,
        # not a catalog item). Insurance is a discrete bill; the rest are smoothed (fuel continuous,
        # maintenance/repair unpredictable).
        _expense( 'Auto Insurance', vehicle, '750', living, semiannual, discrete, mo_yr ),
        _expense( 'Auto Maintenance', vehicle, '300', living, yearly, smooth, mo_yr ),
        _expense( 'Auto Repair', vehicle, '1000', living, yearly, smooth, mo_yr ),
        _expense( 'Gasoline', vehicle, '20', living, weekly, smooth, wk_mo ),
        # Health -- unpredictable medical costs smoothed; the insurance premium a discrete monthly bill.
        _expense( 'Medical Expenses', health, '7200', medical, yearly, smooth, mo_yr ),
        _expense( 'Health Insurance', health, '2200', medical, monthly, discrete, mo_yr ),
        # Miscellaneous -- household costs not tied to a single dwelling; discrete annual bills.
        _expense( 'Umbrella Insurance', misc, '500', living, yearly, discrete, mo_yr ),
        _expense( 'Professional Fees', misc, '500', living, yearly, discrete, mo_yr ),
    ] )


def canonical_defaults() -> dict:
    """All seed presets, keyed by kind then by the variant/scope whose `label` names the set."""
    return {
        ParameterSetKind.ECONOMIC_OUTLOOK: _economic_outlook_presets(),
        ParameterSetKind.EXPENSE_CATALOG: { CatalogScope.GENERAL: _general_expense_catalog() },
    }
