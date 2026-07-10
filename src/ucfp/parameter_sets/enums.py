"""Enums for the parameter-set library."""
from common.labeled_enum import LabeledEnum


class ParameterSetKind( LabeledEnum ):
    """The kind of curated parameter set -- the discriminator for a `ParameterSet`'s payload and
    the registry key for its typed schema."""

    ECONOMIC_OUTLOOK = ( 'Economic Outlook', 'A schedule of economic rate assumptions.' )
    EXPENSE_CATALOG  = ( 'Expense Catalog', 'The curated catalog of expense types and defaults.' )


class ExpenseClass( LabeledEnum ):
    """The applicability scope of a curated expense -- which planning surface it belongs to and the
    decision it attaches to. `LIVING` costs always apply (the recurring Living Expenses table); `PROPERTY`
    costs attach to a dwelling one owns or rents (the Home Expenses matrix); `VEHICLE` costs attach to a
    car (the Vehicle Expenses step). This is the coarse applicability grouping, distinct from
    `ExpenseCategory` -- the finer visual grouping *within* a surface (a single class holds several
    ordered categories)."""

    LIVING   = ( 'Living', 'Everyday household costs that always apply.' )
    PROPERTY = ( 'Property', 'Operating costs of a dwelling one owns or rents.' )
    VEHICLE  = ( 'Vehicle', 'Running costs of owning a car.' )


class ExpenseCategory( LabeledEnum ):
    """The visual grouping of curated expenses within a planning surface -- the ordered section each row
    renders under, finer than its `ExpenseClass` applicability scope. The Living categories, the Property
    sub-groups, and Vehicle are all ordered sections; declaration order (grouped by class below) is the
    section order."""

    # Living -- the always-apply recurring costs (the Living Expenses table).
    EVERYDAY      = ( 'Everyday Living', 'Food, clothing, and the recurring basics.' )
    DISCRETIONARY = ( 'Discretionary', 'Travel, entertainment, hobbies -- the lifestyle spend.' )
    HEALTH        = ( 'Health', 'Medical care and health insurance.' )
    MISCELLANEOUS = ( 'Miscellaneous', 'Household costs not tied to a single dwelling (e.g. umbrella insurance).' )
    # Property -- a dwelling's operating costs (the Home Expenses matrix).
    TAXES_INSURANCE    = ( 'Taxes & Insurance', 'Property tax, insurance, and mandatory ownership dues.' )
    UTILITIES_SERVICES = ( 'Utilities & Services', 'Utilities and recurring household services.' )
    MAINTENANCE_REPAIR = ( 'Maintenance & Repair', 'Upkeep, repairs, and capital replacements.' )
    RENT               = ( 'Rent', 'Rent on a home a tenant occupies but does not own.' )
    # Vehicle -- per-car running costs (the Vehicle Expenses step).
    VEHICLE            = ( 'Vehicle', 'Running costs of owning a car.' )


class PropertyContext( LabeledEnum ):
    """A property situation a catalog `PROPERTY` expense can attach to -- the owned dwelling kinds plus
    a tenant's rented home. A row's `applies_to` names the contexts it seeds against (a roof applies to
    any owned dwelling; utilities also to a rented home; property management only to a rental). The tax
    class is still derived from the actual property at materialization, not from this."""

    RESIDENCE   = ( 'Residence', 'An owned primary residence.' )
    SECOND_HOME = ( 'Second Home', 'An owned second (vacation) home.' )
    RENTAL      = ( 'Rental', 'An owned rental property.' )
    RENTED_HOME = ( 'Rented Home', 'A rented residence a tenant occupies but does not own.' )


class Realization( LabeledEnum ):
    """How an expense's (amount, cadence) becomes engine input -- fixed per expense type, not
    user-editable. `SMOOTH` annualizes and spreads it evenly as a stream (continuous consumption, and
    unpredictable costs where a discrete date would misrepresent). `DISCRETE` places it as a real
    charge at its cadence (predictable, timing-meaningful costs). The two only diverge at yearly+
    cadences; at weekly/monthly they are indistinguishable at forecast granularities."""

    SMOOTH   = ( 'Smoothed', 'Annualized and spread evenly as a continuous stream.' )
    DISCRETE = ( 'Discrete', 'Placed as a charge at its cadence.' )


class CadenceDomain( LabeledEnum ):
    """Which cadences the user may choose for an expense -- the editable input domain, distinct from the
    fixed `Realization`. `FIXED` is not editable (the amount only; the cadence is the seeded one); the
    others let the user pick a magnitude and unit within the named range, reading "Every N units"."""

    FIXED   = ( 'Fixed', 'Not editable; the seeded cadence, amount only.' )
    WK_MO   = ( 'Weekly to monthly', 'Every N weeks or months.' )
    MO_YR   = ( 'Monthly to yearly', 'Every N months or years.' )
    N_YEARS = ( 'Every N years', 'Every N years.' )


class CatalogScope( LabeledEnum ):
    """Which curated expense catalog a scenario draws from -- `GENERAL` is the non-regional default;
    regional catalogs are added as more scopes (the new structure's take on the regional idea the
    lifestyle table carried)."""

    GENERAL = ( 'General', 'The general, non-regional expense catalog.' )


class EconomicOutlookVariant( LabeledEnum ):
    """The named economic outlooks the library ships -- the system defaults a scenario chooses
    among, on a symmetric favorable-to-unfavorable axis. `EXPECTED` is the default. The set may
    gain finer gradations later; nothing should assume exactly three."""

    OPTIMISTIC  = ( 'Optimistic', 'Favorable conditions: stronger returns, milder inflation.' )
    EXPECTED    = ( 'Expected', 'The neutral, most-likely baseline.' )
    PESSIMISTIC = ( 'Pessimistic', 'Cautious conditions: weaker returns, higher inflation.' )
