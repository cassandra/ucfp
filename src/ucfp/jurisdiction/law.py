"""The statute layer the Forecast treats as a black box.

A `StatuteProfile` selects a jurisdiction (`JurisdictionType`), a projection model
(`StatuteForecastType`), and the optional knobs that model needs. `Statute` resolves a profile
and yields the tax engine for any year -- `Statute( profile ).engine_for( year )` -- so the
Forecast chooses *what* to project and drives it year by year without knowing which
figures move or how the engine is built.

This module is the composition point: it is the one place that maps a `JurisdictionType` to a
concrete engine family (US federal today), so it depends on `jurisdiction.us`. The agnostic
`jurisdiction.engine` interface stays free of that dependency.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from common.rate import Rate, ZERO_RATE

from .engine import TaxEngine
from .enums import StatuteForecastType, JurisdictionType
from .us.engine import USFederalTaxEngine
from .us.parameters import BASE_YEAR, federal_2025


@dataclass( frozen = True )
class StatuteProjection:
    """How a jurisdiction is assumed to move its inflation-indexed tax figures over the forecast
    -- a model of government behaviour, not an economic rate. `cola_rate` is the constant annual
    rate the indexed parameters (brackets, deductions, contribution limits, the SS wage base, the
    poverty guideline) grow by: set it at expected inflation for full indexing, below it to model
    the government lagging, or at zero to freeze them. Resolved once at Forecast start and held
    for every period."""

    cola_rate : Rate = ZERO_RATE


@dataclass( frozen = True )
class StatuteProfile:
    """How a forecast's statute is selected and projected: the jurisdiction (`jurisdiction_type`), the
    projection model (`forecast_type`), and the model's knobs. `projection` carries the
    projection assumptions a `COLA_INDEXED` forecast needs (see `StatuteProjection`); `CURRENT_LAW`
    holds the law static and ignores it."""

    jurisdiction_type      : JurisdictionType
    forecast_type : StatuteForecastType
    projection        : Optional[ StatuteProjection ] = None


class Statute:
    """A resolved statute: yields the engine for any year per its forecast profile.

    The composition point -- the one place allowed to map a `JurisdictionType` to a concrete engine
    family (`jurisdiction/us`), so the neutral interface stays agnostic. `engine_for` projects the
    baseline to the year: indexed figures scale by the profile's COLA, statutorily fixed
    thresholds stay put. See `ucfp/FORECAST_ENGINE.md`."""

    def __init__( self, profile : StatuteProfile ):
        self._profile = profile

    def engine_for( self, year : int ) -> TaxEngine:
        """The tax engine in force for `year` under this profile's projection."""
        if self._profile.jurisdiction_type is not JurisdictionType.US_FEDERAL:
            raise NotImplementedError(
                f'Tax law {self._profile.jurisdiction_type} has no engine yet.' )
        if self._profile.forecast_type is StatuteForecastType.CURRENT_LAW:
            return USFederalTaxEngine( federal_2025() )
        if self._profile.forecast_type is StatuteForecastType.COLA_INDEXED:
            return USFederalTaxEngine( federal_2025().indexed( self._cola_factor( year ) ) )
        raise NotImplementedError(
            f'Tax forecast {self._profile.forecast_type} is not supported.' )

    def _cola_factor( self, year : int ) -> Decimal:
        """The cumulative COLA factor from the baseline year to `year` -- the projection's
        `cola_rate` compounded over the elapsed years. A COLA-indexed forecast must supply a
        `projection` (the deliberate government-behaviour assumption)."""
        projection = self._profile.projection
        if projection is None:
            raise ValueError(
                'A COLA-indexed tax forecast requires a projection on the profile.' )
        return projection.cola_rate.compounded( Decimal( year - BASE_YEAR ) ).applied_to( Decimal( '1' ) )
