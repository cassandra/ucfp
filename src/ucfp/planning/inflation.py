"""Restating a run's nominal figures in its start-year ("today's") dollars.

A projected figure is nominal -- the actual dollars in that future year. To read it against money the
viewer knows, it is deflated to the run's start year by the run's own **captured** general-inflation
assumption (never the live scenario), a single constant rate compounded over whole calendar years. This is
the one place that deflation is defined, so the run-summary "Today's $" figure and the charts derive from it
identically. A per-year (time-varying) rate is a possible future refinement; today the rate is constant.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from .schemas import ProjectionRun


def to_todays_dollars( run : ProjectionRun, amount : Decimal, at_date : date ) -> Optional[ Decimal ]:
    """`amount` -- a nominal figure at `at_date` -- restated in `run`'s start-year dollars, or None when the
    restatement is a no-op (nothing to discount): a zero/absent inflation assumption, or a figure at or
    before the start year. The companion-figure form for a nominal/real pair that omits the real line when it
    would add nothing; for a chart's series use `deflation_factor` (always a number)."""
    inflation, years = _inflation_and_years( run, at_date )
    if inflation <= 0 or years <= 0:
        return None
    return amount / ( ( Decimal( '1' ) + inflation ) ** years )


def deflation_factor( run : ProjectionRun, at_date : date ) -> Decimal:
    """The factor to multiply a nominal figure at `at_date` by to restate it in `run`'s start-year dollars:
    1 / (1+i)**years. 1 (identity) when there is nothing to discount, so it is always safe to apply -- this
    is the per-point building block for deflating a whole series (e.g. a chart's per-span values)."""
    inflation, years = _inflation_and_years( run, at_date )
    if inflation <= 0 or years <= 0:
        return Decimal( '1' )
    return Decimal( '1' ) / ( ( Decimal( '1' ) + inflation ) ** years )


def _inflation_and_years( run : ProjectionRun, at_date : date ) -> tuple:
    """The run's constant general-inflation rate and the whole calendar years from its start to `at_date` --
    the two inputs both deflation forms share. A missing assumptions set reads as zero inflation."""
    economics = run.assumptions.economics if run.assumptions else None
    inflation = economics.inflation.fraction if economics else Decimal( '0' )
    return inflation, at_date.year - run.frame.start_date.year
