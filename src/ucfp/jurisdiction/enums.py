"""General enums for the jurisdiction layer: the statute selectors (which jurisdiction, how it is
projected -- bundled by `StatuteProfile` in `law.py`) and the taxpayer classification a
jurisdiction's engine reads. These are jurisdiction-agnostic concepts; a country's engine uses
them or ignores them (e.g. a jurisdiction with no joint return simply never sees `MARRIED_JOINT`).
"""
from common.labeled_enum import LabeledEnum


class JurisdictionType( LabeledEnum ):
    """Which jurisdiction's statute (and so which engine family)."""

    US_FEDERAL = ( 'US Federal', 'United States federal income tax.' )


class StatuteForecastType( LabeledEnum ):
    """How the chosen statute is projected forward over the forecast horizon."""

    CURRENT_LAW  = ( "Freeze today's brackets",
                     "Today's brackets and thresholds are held flat every future year; as incomes grow, "
                     "more income falls into higher brackets -- a more conservative, higher-tax assumption." )
    COLA_INDEXED = ( 'Brackets rise with inflation',
                     'Tax brackets and the standard deduction grow each year with inflation, as they do '
                     'under current law.' )


class FilingStatus( LabeledEnum ):
    """A taxpayer's filing classification -- the household's standing status, which a
    jurisdiction's engine maps onto its own rules (brackets, thresholds, deductions)."""

    MARRIED_JOINT = ( 'Married Filing Jointly' , 'A married couple filing one joint return.' )
    SINGLE        = ( 'Single'                 , 'An unmarried individual filing alone.' )


class JurisdictionConcept( LabeledEnum ):
    """A domain concept whose everyday name varies by jurisdiction. The label here is the neutral,
    jurisdiction-agnostic name the app uses by default; a jurisdiction's local term (e.g. a government
    pension is "Social Security" in the US) is resolved separately in `labels.py`, so US-specific
    wording stays out of the shared forms and templates."""

    GOVERNMENT_PENSION  = ( 'Government pension',
                            'A government social-insurance retirement benefit.' )
    SUBSIDIZED_HEALTH   = ( 'Subsidized health coverage',
                            'Means-tested subsidized health insurance.' )
    PRETAX_RETIREMENT   = ( 'Pre-tax retirement',
                            'A tax-deferred retirement account; withdrawals are ordinary income.' )
    TAX_FREE_RETIREMENT = ( 'Tax-free retirement',
                            'An after-tax retirement account; qualified growth is tax-free.' )
