"""Enums for the parameter-set library."""
from common.labeled_enum import LabeledEnum


class ParameterSetKind( LabeledEnum ):
    """The kind of curated parameter set -- the discriminator for a `ParameterSet`'s payload and
    the registry key for its typed schema."""

    ECONOMIC_OUTLOOK = ( 'Economic Outlook', 'A schedule of economic rate assumptions.' )
    LIFESTYLE_COSTS  = ( 'Lifestyle Costs', 'A table of discretionary expenses by lifestyle level.' )
    EXPENSE_CATALOG  = ( 'Expense Catalog', 'The curated catalog of expense types and defaults.' )


class LifestyleLevel( LabeledEnum ):
    """A spending tier a user schedules over time -- the uniform selector that indexes each
    lifestyle expense's low/medium/high value."""

    HIGH   = ( 'High'  , 'An expansive lifestyle: more travel, dining, discretionary spend.' )
    MEDIUM = ( 'Medium', 'A moderate, typical lifestyle.' )
    LOW    = ( 'Low'   , 'A lean lifestyle: reduced discretionary spend.' )


class LifestyleScope( LabeledEnum ):
    """Which curated lifestyle cost table a scenario draws from -- the table's identity, not a
    level. `GENERAL` is the non-regional default; regional tables are added as more scopes."""

    GENERAL = ( 'General', 'The general, non-regional cost table.' )


class ExpenseCategory( LabeledEnum ):
    """How curated expenses group in the interview -- the user-facing buckets, and the decision each
    attaches to: Home costs to owning a home, Auto to a vehicle, Utilities to a residence; Everyday,
    Discretionary, and Health always apply."""

    EVERYDAY      = ( 'Everyday Living', 'Food, clothing, and the recurring basics.' )
    DISCRETIONARY = ( 'Discretionary', 'Travel, entertainment, hobbies -- the lifestyle spend.' )
    UTILITIES     = ( 'Utilities', 'Water, power, phone, and internet for a residence.' )
    HOME          = ( 'Home', 'Costs of owning a home: insurance, upkeep, property tax.' )
    AUTO          = ( 'Auto', 'Costs of owning a vehicle.' )
    HEALTH        = ( 'Health', 'Medical care and health insurance.' )
    GIVING        = ( 'Giving', 'Charitable contributions.' )
    RENTAL        = ( 'Rental', 'Operating costs of a rental property.' )


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
