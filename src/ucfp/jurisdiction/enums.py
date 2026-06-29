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

    CURRENT_LAW  = ( 'Current Law', 'The current year law applied unchanged every year.' )
    COLA_INDEXED = ( 'COLA-Indexed', 'Inflation-indexed figures shift each year; statutory '
                                     'fixed figures stay put.' )


class FilingStatus( LabeledEnum ):
    """A taxpayer's filing classification -- the household's standing status, which a
    jurisdiction's engine maps onto its own rules (brackets, thresholds, deductions)."""

    MARRIED_JOINT = ( 'Married Filing Jointly' , 'A married couple filing one joint return.' )
    SINGLE        = ( 'Single'                 , 'An unmarried individual filing alone.' )
