"""Enums for the parameter-set library."""
from common.labeled_enum import LabeledEnum


class ParameterSetKind( LabeledEnum ):
    """The kind of curated parameter set -- the discriminator for a `ParameterSet`'s payload and
    the registry key for its typed schema."""

    ECONOMIC_OUTLOOK = ( 'Economic Outlook', 'A schedule of economic rate assumptions.' )
    EXPENSE_CATALOG  = ( 'Expense Catalog', 'The curated catalog of expense types and defaults.' )


class ExpenseCategory( LabeledEnum ):
    """How curated expenses group in the interview -- the user-facing buckets, and the decision each
    attaches to: Property costs to a dwelling one owns or rents, Vehicle to a car; Everyday,
    Discretionary, Health, and Miscellaneous always apply."""

    EVERYDAY      = ( 'Everyday Living', 'Food, clothing, and the recurring basics.' )
    DISCRETIONARY = ( 'Discretionary', 'Travel, entertainment, hobbies -- the lifestyle spend.' )
    PROPERTY      = ( 'Property', 'Operating costs of a dwelling -- upkeep, insurance, utilities, property tax -- one set per owned property, taxed by its type.' )
    VEHICLE       = ( 'Vehicle', 'Running costs of owning a car.' )
    HEALTH        = ( 'Health', 'Medical care and health insurance.' )
    GIVING        = ( 'Giving', 'Charitable contributions.' )
    MISCELLANEOUS = ( 'Miscellaneous', 'Household costs not tied to a single dwelling (e.g. umbrella insurance).' )


class PropertyContext( LabeledEnum ):
    """A property situation a catalog `PROPERTY` expense can attach to -- the owned dwelling kinds plus
    a tenant's rented home. A row's `applies_to` names the contexts it seeds against (a roof applies to
    any owned dwelling; utilities also to a rented home; property management only to a rental). The tax
    class is still derived from the actual property at materialization, not from this."""

    RESIDENCE   = ( 'Residence', 'An owned primary residence.' )
    SECOND_HOME = ( 'Second Home', 'An owned second (vacation) home.' )
    RENTAL      = ( 'Rental', 'An owned rental property.' )
    RENTED_HOME = ( 'Rented Home', 'A rented residence a tenant occupies but does not own.' )


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
