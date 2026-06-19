"""The Economic Outlook: the global VALUE-axis assumptions a Forecast projects under.

An outlook is a **schedule** -- a list of `EconomicParameters` segments, each carrying its
own `[start, end]` window like the other time-bound inputs. A run with one set of rates for
the whole horizon is just a single unbounded segment (`EconomicOutlook.constant`); pinning
different rates to different year ranges is more segments.

The Forecast resolves the segment in effect for each interval (by the interval's start
date) into that period's `AssetRates`, so the Period's growth and distribution steps fire.

STUB: income-side COLAs (Social Security, pensions, rent) live with the income inputs;
precious-metals / collectibles / depreciating rates and a retirement asset-mix join as
needed. Segments are resolved at period boundaries (no sub-period rate changes).
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from common.rate import ZERO_RATE, Rate
from ucfp.accounts.enums import AssetClass
from ucfp.period.parameters import AssetRates


@dataclass( frozen = True )
class EconomicParameters:
    """The economic rates in effect over one window `[start, end]` (inclusive; `None` on a
    side = unbounded). Holds inflation and the per-asset-class appreciation (growth) and
    yield (distribution) rates in the spreadsheet's vocabulary; `asset_rates` maps them to
    the Period's per-`AssetClass` rates. The window rides here -- like the other time-bound
    inputs -- so an `EconomicOutlook` is just a list of these."""

    start                    : Optional[ date ] = None
    end                      : Optional[ date ] = None
    inflation                : Rate = ZERO_RATE
    savings_interest         : Rate = ZERO_RATE   # CASH yield (distribution)
    cd_interest              : Rate = ZERO_RATE   # CDS yield
    bond_appreciation        : Rate = ZERO_RATE   # BONDS price growth
    bond_interest            : Rate = ZERO_RATE   # BONDS coupon (distribution)
    stock_appreciation       : Rate = ZERO_RATE   # STOCKS + DIVIDEND_STOCKS growth
    stock_dividend           : Rate = ZERO_RATE   # DIVIDEND_STOCKS yield
    real_estate_appreciation : Rate = ZERO_RATE   # residence + rental growth
    retirement_growth        : Rate = ZERO_RATE   # PRETAX_RETIREMENT + ROTH (blended)

    def covers( self, on_date : date ) -> bool:
        """Whether this segment's window contains `on_date`."""
        if ( self.start is not None ) and ( on_date < self.start ):
            return False
        if ( self.end is not None ) and ( on_date > self.end ):
            return False
        return True

    def asset_rates( self ) -> AssetRates:
        """Resolve into the Period's per-`AssetClass` growth and distribution rates. A
        class absent from a map carries a zero rate (the `AssetRates` default), so precious
        metals, collectibles, and depreciating assets simply do not move yet."""
        growth = {
            AssetClass.STOCKS                : self.stock_appreciation,
            AssetClass.DIVIDEND_STOCKS       : self.stock_appreciation,
            AssetClass.BONDS                 : self.bond_appreciation,
            AssetClass.REAL_ESTATE_RESIDENCE : self.real_estate_appreciation,
            AssetClass.REAL_ESTATE_RENTAL    : self.real_estate_appreciation,
            AssetClass.PRETAX_RETIREMENT     : self.retirement_growth,
            AssetClass.ROTH                  : self.retirement_growth,
        }
        distribution = {
            AssetClass.CASH            : self.savings_interest,
            AssetClass.CDS             : self.cd_interest,
            AssetClass.BONDS           : self.bond_interest,
            AssetClass.DIVIDEND_STOCKS : self.stock_dividend,
        }
        return AssetRates( growth = growth, distribution = distribution )


# Flat (all-zero, unbounded) parameters: the fallback where no segment covers a date.
_FLAT_PARAMETERS = EconomicParameters()


@dataclass( frozen = True )
class EconomicOutlook:
    """A schedule of `EconomicParameters` segments over the horizon. The Forecast asks for
    the segment in effect on an interval's start date; where none covers, rates are flat
    zero. Order is priority -- the first covering segment wins, so callers keep segments
    non-overlapping (or rely on first-match)."""

    segments : tuple[ EconomicParameters, ... ] = ()

    @classmethod
    def constant( cls, parameters : EconomicParameters ) -> 'EconomicOutlook':
        """One set of rates for the whole horizon (a single unbounded segment)."""
        return cls( segments = ( parameters, ) )

    def parameters_at( self, on_date : date ) -> EconomicParameters:
        """The first segment covering `on_date`, or flat-zero parameters if none do."""
        for segment in self.segments:
            if segment.covers( on_date ):
                return segment
            continue
        return _FLAT_PARAMETERS

    def asset_rates_at( self, on_date : date ) -> AssetRates:
        """The Period `AssetRates` in effect on `on_date`."""
        return self.parameters_at( on_date ).asset_rates()
