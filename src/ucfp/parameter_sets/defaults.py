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
    CadenceDomain, CatalogScope, EconomicOutlookVariant, ExpenseCategory, ExpenseClass,
    ParameterSetKind, PropertyContext, Realization )
from .schemas import EconomicOutlookSchedule, ExpenseCatalog, ExpenseType


def _rate( value : str ) -> Rate:
    return Rate( Decimal( value ) )


def _economic_outlook_presets() -> dict:
    return {
        EconomicOutlookVariant.OPTIMISTIC: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                    = _rate( '0.02' ),
            medical_inflation            = _rate( '0.04' ),
            wage_growth                  = _rate( '0.035' ),
            savings_interest             = _rate( '0.025' ),
            cd_interest                  = _rate( '0.035' ),
            bond_interest                = _rate( '0.045' ),
            stock_appreciation           = _rate( '0.075' ),
            stock_dividend               = _rate( '0.02' ),
            real_estate_appreciation     = _rate( '0.045' ),
            precious_metals_appreciation = _rate( '0.04' ),
            collectibles_appreciation    = _rate( '0.03' ),
            depreciation_rate            = _rate( '0.15' ),
            retirement_growth            = _rate( '0.07' ),
            social_security_cola         = _rate( '0.025' ),
            pension_cola                 = _rate( '0.025' ),
            rental_increase              = _rate( '0.035' ),
        ) ] ),
        EconomicOutlookVariant.EXPECTED: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                    = _rate( '0.025' ),
            medical_inflation            = _rate( '0.045' ),
            wage_growth                  = _rate( '0.03' ),
            savings_interest             = _rate( '0.02' ),
            cd_interest                  = _rate( '0.03' ),
            bond_interest                = _rate( '0.04' ),
            stock_appreciation           = _rate( '0.06' ),
            stock_dividend               = _rate( '0.018' ),
            real_estate_appreciation     = _rate( '0.035' ),
            precious_metals_appreciation = _rate( '0.03' ),
            collectibles_appreciation    = _rate( '0.02' ),
            depreciation_rate            = _rate( '0.18' ),
            retirement_growth            = _rate( '0.055' ),
            social_security_cola         = _rate( '0.025' ),
            pension_cola                 = _rate( '0.02' ),
            rental_increase              = _rate( '0.03' ),
        ) ] ),
        EconomicOutlookVariant.PESSIMISTIC: EconomicOutlookSchedule( [ EconomicParameters(
            inflation                    = _rate( '0.03' ),
            medical_inflation            = _rate( '0.05' ),
            wage_growth                  = _rate( '0.025' ),
            savings_interest             = _rate( '0.015' ),
            cd_interest                  = _rate( '0.025' ),
            bond_interest                = _rate( '0.035' ),
            stock_appreciation           = _rate( '0.045' ),
            stock_dividend               = _rate( '0.018' ),
            real_estate_appreciation     = _rate( '0.025' ),
            precious_metals_appreciation = _rate( '0.02' ),
            collectibles_appreciation    = _rate( '0.01' ),
            depreciation_rate            = _rate( '0.20' ),
            retirement_growth            = _rate( '0.04' ),
            social_security_cola         = _rate( '0.02' ),
            pension_cola                 = _rate( '0.0' ),
            rental_increase              = _rate( '0.025' ),
        ) ] ),
    }


# Each visual `ExpenseCategory` belongs to exactly one applicability `ExpenseClass` (the surface it
# shows on). The class is a stored `ExpenseType` field, resolved here from the category so the catalog
# author names the category once and the two cannot drift.
_CLASS_BY_CATEGORY = {
    ExpenseCategory.EVERYDAY           : ExpenseClass.LIVING,
    ExpenseCategory.DISCRETIONARY      : ExpenseClass.LIVING,
    ExpenseCategory.HEALTH             : ExpenseClass.LIVING,
    ExpenseCategory.MISCELLANEOUS      : ExpenseClass.LIVING,
    ExpenseCategory.TAXES_INSURANCE    : ExpenseClass.PROPERTY,
    ExpenseCategory.UTILITIES_SERVICES : ExpenseClass.PROPERTY,
    ExpenseCategory.MAINTENANCE_REPAIR : ExpenseClass.PROPERTY,
    ExpenseCategory.RENT               : ExpenseClass.PROPERTY,
    ExpenseCategory.VEHICLE            : ExpenseClass.VEHICLE,
}


def _expense( name : str, handle : str, category, order : int, amount : str, tax_class, interval,
              realization, domain, applies_to : tuple = () ) -> ExpenseType:
    return ExpenseType(
        name = name, handle = handle, expense_class = _CLASS_BY_CATEGORY[ category ], category = category,
        order = order, expense_tax_class = tax_class, default_amount = Decimal( amount ),
        interval = interval, realization = realization, cadence_domain = domain, applies_to = applies_to )


def _durable( name : str, handle : str, category, order : int, count : int, cost_each : str,
              lifespan : int, tax_class, applies_to : tuple = () ) -> ExpenseType:
    """A durable-replacement expense entered as `count` items at `cost_each`, replaced every `lifespan`
    years. Its amount is the annualized cost (count x cost_each / lifespan) -- a calculator fills it --
    so it materializes as a smoothed yearly stream (staggered replacements average out); the cadence is
    a fixed yearly, the replacement lifespan being a calculator input, not the expense's interval."""
    cost   = Decimal( cost_each )
    annual = count * cost / lifespan
    return ExpenseType(
        name = name, handle = handle, expense_class = _CLASS_BY_CATEGORY[ category ], category = category,
        order = order, expense_tax_class = tax_class, default_amount = annual,
        interval = Duration( 1, TimeUnit.YEAR ), realization = Realization.SMOOTH,
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
    health        = ExpenseCategory.HEALTH
    misc          = ExpenseCategory.MISCELLANEOUS
    taxes         = ExpenseCategory.TAXES_INSURANCE
    utilities     = ExpenseCategory.UTILITIES_SERVICES
    upkeep        = ExpenseCategory.MAINTENANCE_REPAIR
    rent_cat      = ExpenseCategory.RENT
    vehicle       = ExpenseCategory.VEHICLE
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
    # Rows are authored grouped by category with an explicit per-category `order`; the rendered
    # (group, item) order is (category declaration order, order), independent of the authoring order here.
    return ExpenseCatalog( [
        # --- Living: everyday -- continuous consumption, smoothed; entered weekly or monthly.
        _expense( 'Food', 'food', everyday, 10, '170', living, weekly, smooth, wk_mo ),
        _expense( 'Consumables', 'consumables', everyday, 20, '28', living, weekly, smooth, wk_mo ),
        _expense( 'Clothes', 'clothes', everyday, 30, '1800', living, yearly, smooth, mo_yr ),
        _expense( 'Grooming', 'grooming', everyday, 40, '960', living, yearly, smooth, mo_yr ),
        # --- Living: discretionary -- smoothed budgets, subscriptions (fixed monthly), discrete events.
        _expense( 'Vacations', 'vacations', discretionary, 10, '10000', living, yearly, discrete, mo_yr ),
        _expense( 'Transportation / Travel', 'travel', discretionary, 20, '0', living, quarterly, smooth, mo_yr ),
        _expense( 'Dining Out', 'dining-out', discretionary, 30, '85', living, weekly, smooth, wk_mo ),
        _expense( 'Entertainment', 'entertainment', discretionary, 40, '50', living, weekly, smooth, wk_mo ),
        _expense( 'Cable TV / Streaming', 'cable-streaming', discretionary, 50, '100', living, monthly, discrete, fixed ),
        _expense( 'Hobbies', 'hobbies', discretionary, 60, '150', living, quarterly, smooth, mo_yr ),
        _durable( 'Computer Purchase', 'computer-purchase', discretionary, 70, 2, '1500', 4, living ),
        _expense( 'Computer Services', 'computer-services', discretionary, 80, '300', living, yearly, smooth, mo_yr ),
        _expense( 'Gifts', 'gifts', discretionary, 90, '3000', living, yearly, smooth, mo_yr ),
        _expense( 'Health & Fitness', 'health-fitness', discretionary, 100, '70', living, monthly, discrete, fixed ),
        _expense( 'Furniture', 'furniture', discretionary, 110, '700', living, yearly, smooth, mo_yr ),
        # --- Living: health -- unpredictable medical costs smoothed; the premium a discrete monthly bill.
        _expense( 'Medical Expenses', 'medical-expenses', health, 10, '4500', medical, yearly, smooth, mo_yr ),
        _expense( 'Health Insurance', 'health-insurance', health, 20, '550', medical, monthly, discrete, mo_yr ),
        # --- Living: miscellaneous -- household costs not tied to a single dwelling; discrete annual bills.
        _expense( 'Umbrella Insurance', 'umbrella-insurance', misc, 10, '500', living, yearly, discrete, mo_yr ),
        _expense( 'Professional Fees', 'professional-fees', misc, 20, '500', living, yearly, discrete, mo_yr ),
        # Property rows are one operating-cost set seeded per owned dwelling. Tax class is the PERSONAL
        # class (property tax -> SALT, the rest -> living); materialization swaps it to a rental expense
        # for a rental. `applies_to` scopes each row: owned dwellings, occupied (owned plus a tenant's
        # rented home, for utilities), a rented home alone (rent), or an owned rental alone (management).
        # --- Property: taxes & insurance -- tax/insurance let the user pick monthly (escrow) or yearly.
        _expense( 'Property Tax', 'property-tax', taxes, 10, '5500', salt, yearly, discrete, mo_yr, applies_to = owned ),
        _expense( 'Property Insurance', 'property-insurance', taxes, 20, '2500', living, yearly, discrete, mo_yr, applies_to = owned ),
        _expense( 'HOA / Coop Fee', 'hoa-fee', taxes, 30, '0', living, monthly, discrete, fixed, applies_to = owned ),
        # --- Property: utilities & services -- fixed monthly bills; utilities also seed a rented home.
        _expense( 'Water / Wastewater', 'water', utilities, 10, '90', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Electric', 'electric', utilities, 20, '150', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Gas Utility', 'gas-utility', utilities, 30, '80', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Phone Service', 'phone-service', utilities, 40, '100', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Internet', 'internet', utilities, 50, '80', living, monthly, discrete, fixed, applies_to = occupied ),
        _expense( 'Property Management', 'property-management', utilities, 60, '240', rental_expense, monthly, discrete, fixed, applies_to = rental_only ),
        # --- Property: maintenance & repair -- ongoing upkeep, then the capital replacements (durables).
        _expense( 'Maintenance / Repair', 'maintenance-repair', upkeep, 10, '250', living, monthly, smooth, mo_yr, applies_to = owned ),
        _expense( 'Pest Control', 'pest-control', upkeep, 20, '110', living, quarterly, discrete, fixed, applies_to = owned ),
        _expense( 'Pool Maintenance', 'pool-maintenance', upkeep, 30, '0', living, monthly, discrete, fixed, applies_to = owned ),
        _expense( 'Lawn Maintenance', 'lawn-maintenance', upkeep, 40, '0', living, monthly, discrete, fixed, applies_to = owned ),
        _durable( 'Lawn Tools', 'lawn-tools', upkeep, 50, 4, '500', 20, living, applies_to = owned ),
        _expense( 'A/C Cost', 'ac-cost', upkeep, 60, '9000', living, every_15y, smooth, n_years, applies_to = owned ),
        _durable( 'Appliance', 'appliance', upkeep, 70, 3, '2900', 15, living, applies_to = owned ),
        _expense( 'Roof Cost', 'roof-cost', upkeep, 80, '15000', living, every_20y, smooth, n_years, applies_to = owned ),
        # --- Property: rent -- a tenant's rented home only.
        _expense( 'Rent', 'rent', rent_cat, 10, '1600', living, monthly, discrete, fixed, applies_to = rented_only ),
        # Vehicle running costs seed the per-car running costs of the Vehicle Expenses step (applied at
        # materialization to each owned vehicle over its window); the car purchase/financing itself is
        # entered per vehicle, not a catalog item. Insurance is a discrete bill; the rest are smoothed
        # (fuel continuous, maintenance/repair unpredictable).
        _expense( 'Insurance', 'auto-insurance', vehicle, 10, '850', living, semiannual, discrete, mo_yr ),
        _expense( 'Maintenance', 'auto-maintenance', vehicle, 20, '300', living, yearly, smooth, mo_yr ),
        _expense( 'Repairs', 'auto-repair', vehicle, 30, '1000', living, yearly, smooth, mo_yr ),
        _expense( 'Fuel', 'gasoline', vehicle, 40, '30', living, weekly, smooth, wk_mo ),
    ] )


def canonical_defaults() -> dict:
    """All seed presets, keyed by kind then by the variant/scope whose `label` names the set."""
    return {
        ParameterSetKind.ECONOMIC_OUTLOOK: _economic_outlook_presets(),
        ParameterSetKind.EXPENSE_CATALOG: { CatalogScope.GENERAL: _general_expense_catalog() },
    }
