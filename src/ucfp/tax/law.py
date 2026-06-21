"""The tax-law layer the Forecast treats as a black box.

A `TaxForecastProfile` selects a jurisdiction (`TaxLawType`), a projection model
(`TaxForecastType`), and the optional knobs that model needs. `TaxLaw` resolves a profile
and yields the tax engine for any year -- `TaxLaw( profile ).engine_for( year )` -- so the
Forecast chooses *what* to project and drives it year by year without knowing which
figures move or how the engine is built.

This module is the composition point: it is the one place that maps a `TaxLawType` to a
concrete engine family (US federal today), so it depends on `tax.us`. The agnostic
`tax.engine` interface stays free of that dependency.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from common.rate import Rate, ZERO_RATE

from .engine import TaxEngine
from .enums import TaxForecastType, TaxLawType
from .us.engine import USFederalTaxEngine
from .us.parameters import BASE_YEAR, federal_2025


@dataclass( frozen = True )
class TaxProjection:
    """How a jurisdiction is assumed to move its inflation-indexed tax figures over the forecast
    -- a model of government behaviour, not an economic rate. `cola_rate` is the constant annual
    rate the indexed parameters (brackets, deductions, contribution limits, the SS wage base, the
    poverty guideline) grow by: set it at expected inflation for full indexing, below it to model
    the government lagging, or at zero to freeze them. Resolved once at Forecast start and held
    for every period. A value object so further projection knobs (per-figure freezes, statutory
    what-ifs) can join without disturbing callers."""

    cola_rate : Rate = ZERO_RATE


@dataclass( frozen = True )
class TaxForecastProfile:
    """How a forecast's tax law is selected and projected: the jurisdiction (`tax_law_type`), the
    projection model (`tax_forecast_type`), and the model's knobs. `projection` carries the
    projection assumptions a `COLA_INDEXED` forecast needs (see `TaxProjection`); `CURRENT_LAW`
    holds the law static and ignores it."""

    tax_law_type      : TaxLawType
    tax_forecast_type : TaxForecastType
    projection        : Optional[ TaxProjection ] = None


class TaxLaw:
    """A resolved tax law: yields the engine for any year per its forecast profile."""

    def __init__( self, profile : TaxForecastProfile ):
        self._profile = profile

    def engine_for( self, year : int ) -> TaxEngine:
        """The tax engine in force for `year` under this profile's projection."""
        if self._profile.tax_law_type is not TaxLawType.US_FEDERAL:
            raise NotImplementedError(
                f'Tax law {self._profile.tax_law_type} has no engine yet.' )
        if self._profile.tax_forecast_type is TaxForecastType.CURRENT_LAW:
            return USFederalTaxEngine( federal_2025() )
        if self._profile.tax_forecast_type is TaxForecastType.COLA_INDEXED:
            return USFederalTaxEngine( federal_2025().indexed( self._cola_factor( year ) ) )
        raise NotImplementedError(
            f'Tax forecast {self._profile.tax_forecast_type} is not supported.' )

    def _cola_factor( self, year : int ) -> Decimal:
        """The cumulative COLA factor from the baseline year to `year` -- the projection's
        `cola_rate` compounded over the elapsed years. A COLA-indexed forecast must supply a
        `projection` (the deliberate government-behaviour assumption; a fall-back to the Economic
        Outlook's inflation is a later wiring)."""
        projection = self._profile.projection
        if projection is None:
            raise ValueError(
                'A COLA-indexed tax forecast requires a projection on the profile.' )
        return projection.cola_rate.compounded( Decimal( year - BASE_YEAR ) ).applied_to( Decimal( '1' ) )
