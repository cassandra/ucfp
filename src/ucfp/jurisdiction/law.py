"""The statute layer the Forecast treats as a black box.

A `StatuteProfile` pairs a jurisdiction (`JurisdictionType`, a Profile fact) with a `TaxProjection`
(a projection model `StatuteForecastType` and its optional knobs, an Assumptions forward-view),
composed at materialization. `Statute` resolves a profile and yields the tax engine for any year --
`Statute( profile ).engine_for( year )` -- so the Forecast chooses *what* to project and drives it
year by year without knowing which figures move or how the engine is built.

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
from .us.subdivision_tax import StateIncomeTax
from .us.parameters import BASE_YEAR, federal_2026


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
class TaxProjection:
    """How a jurisdiction's tax law is projected forward -- the forward-view (assumption) half of a
    statute, independent of which jurisdiction it applies to, so it lives with the Assumptions and can
    be varied over one situation (an Optimistic vs Pessimistic outlook). `forecast_type` selects the
    projection model; `projection` carries that model's knobs -- a `COLA_INDEXED` forecast needs a
    `StatuteProjection`, while `CURRENT_LAW` holds the law static and ignores it."""

    forecast_type : StatuteForecastType
    projection    : Optional[ StatuteProjection ] = None


@dataclass( frozen = True )
class StatuteProfile:
    """The statute the engine resolves: which jurisdiction's law (`jurisdiction_type` -- a fact about
    the household, sourced from the Profile) projected how (`tax_projection` -- the forward view,
    sourced from the Assumptions). Composed at materialization from those two aggregates; the engine
    treats the result as a black box.

    `state_income_tax` is the simplified per-state surcharge -- a flat rate on federal AGI less the
    state's exemption of retirement income (Social Security, pensions, withdrawals), composed at
    materialization from the Profile's chosen state and (overridable) rate. Its default is no state
    income tax."""

    jurisdiction_type : JurisdictionType
    tax_projection    : TaxProjection
    state_income_tax  : StateIncomeTax = StateIncomeTax()


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
        forecast_type = self._profile.tax_projection.forecast_type
        # The flat state surcharge is the same every year (not projected), so both branches pass it
        # through unchanged; only the federal parameters differ by projection.
        state_tax     = self._profile.state_income_tax
        if forecast_type is StatuteForecastType.CURRENT_LAW:
            return USFederalTaxEngine( federal_2026(), state_tax )
        if forecast_type is StatuteForecastType.COLA_INDEXED:
            return USFederalTaxEngine(
                federal_2026().indexed( self._cola_factor( year ) ), state_tax )
        raise NotImplementedError(
            f'Tax forecast {forecast_type} is not supported.' )

    def _cola_factor( self, year : int ) -> Decimal:
        """The cumulative COLA factor from the baseline year to `year` -- the projection's
        `cola_rate` compounded over the elapsed years. A COLA-indexed forecast must supply a
        `projection` (the deliberate government-behaviour assumption)."""
        projection = self._profile.tax_projection.projection
        if projection is None:
            raise ValueError(
                'A COLA-indexed tax forecast requires a projection on the profile.' )
        return projection.cola_rate.compounded( Decimal( year - BASE_YEAR ) ).applied_to( Decimal( '1' ) )
