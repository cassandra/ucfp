"""Selectors for the tax-law layer: which jurisdiction's law, and how it is projected
over a forecast. A `TaxForecastProfile` (see `law.py`) bundles these with the optional
knobs a projection needs; the Forecast picks a profile and treats the resulting engine
as a black box.
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
