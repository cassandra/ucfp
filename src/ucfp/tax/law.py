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

from .engine import TaxEngine
from .enums import TaxForecastType, TaxLawType
from .us.engine import USFederalTaxEngine
from .us.parameters import federal_2025


@dataclass( frozen = True )
class TaxForecastProfile:
    """How a forecast's tax law is selected and projected. `tax_cola_rate` is the first
    optional knob (the COLA that `COLA_INDEXED` shifts indexed figures by); when unset it
    will fall back to the Economic Outlook's inflation once that exists. Other models add
    their own optional knobs here as they arrive."""

    tax_law_type      : TaxLawType
    tax_forecast_type : TaxForecastType
    tax_cola_rate     : Decimal = None


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
            raise NotImplementedError( 'COLA-indexed tax forecast is not yet built.' )
        raise NotImplementedError(
            f'Tax forecast {self._profile.tax_forecast_type} is not supported.' )
