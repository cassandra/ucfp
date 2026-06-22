"""General enums for the tax layer: the tax-law selectors (which jurisdiction, how it is
projected -- bundled by `TaxForecastProfile` in `law.py`) and the taxpayer classification a
jurisdiction's engine reads. These are jurisdiction-agnostic concepts; a country's engine uses
them or ignores them (e.g. a jurisdiction with no joint return simply never sees `MARRIED_JOINT`).
"""
from common.labeled_enum import LabeledEnum


class TaxLawType( LabeledEnum ):
    """Which jurisdiction's tax law (and so which engine family)."""

    US_FEDERAL = ( 'US Federal', 'United States federal income tax.' )


class TaxForecastType( LabeledEnum ):
    """How the chosen tax law is projected forward over the forecast horizon."""

    CURRENT_LAW  = ( 'Current Law', 'The current year law applied unchanged every year.' )
    COLA_INDEXED = ( 'COLA-Indexed', 'Inflation-indexed figures shift each year; statutory '
                                     'fixed figures stay put.' )


class FilingStatus( LabeledEnum ):
    """A taxpayer's filing classification -- the household's standing status, which a
    jurisdiction's engine maps onto its own rules (brackets, thresholds, deductions)."""

    MARRIED_JOINT = ( 'Married Filing Jointly' , 'A married couple filing one joint return.' )
    SINGLE        = ( 'Single'                 , 'An unmarried individual filing alone.' )
