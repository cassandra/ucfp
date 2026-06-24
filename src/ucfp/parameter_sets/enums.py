"""Enums for the parameter-set library."""
from common.labeled_enum import LabeledEnum


class ParameterSetKind( LabeledEnum ):
    """The kind of curated parameter set -- the discriminator for a `ParameterSet`'s payload and
    the registry key for its typed schema."""

    ECONOMIC_OUTLOOK = ( 'Economic Outlook', 'A schedule of economic rate assumptions.' )
    LIFESTYLE_COSTS  = ( 'Lifestyle Costs', 'A table of discretionary expenses by lifestyle level.' )


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


class EconomicOutlookVariant( LabeledEnum ):
    """The named economic outlooks the library ships -- the system defaults a scenario chooses
    among, on a symmetric favorable-to-unfavorable axis. `EXPECTED` is the default. The set may
    gain finer gradations later; nothing should assume exactly three."""

    OPTIMISTIC  = ( 'Optimistic', 'Favorable conditions: stronger returns, milder inflation.' )
    EXPECTED    = ( 'Expected', 'The neutral, most-likely baseline.' )
    PESSIMISTIC = ( 'Pessimistic', 'Cautious conditions: weaker returns, higher inflation.' )
