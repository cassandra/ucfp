"""A calendar date span -- a foundational value object shared across the Period and Forecast.

Kept in its own leaf module (depending only on the standard library) so both `PeriodParameters`
and `FiscalWindow` can use it without importing each other -- the seam that lets the Forecast
hand a resolved `FiscalWindow` to the Period through `PeriodParameters`.
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass( frozen = True )
class DateSpan:
    """An inclusive [start_date, end_date] calendar span."""

    start_date : date
    end_date   : date

    @property
    def day_before_start( self ) -> date:
        """The day immediately before the span -- the point through which opening
        balances are read (the prior period's close)."""
        return self.start_date - timedelta( days = 1 )

    @property
    def midpoint( self ) -> date:
        """The span's midpoint date; events default here (the mid-period convention)."""
        return self.start_date + timedelta( days = ( self.end_date - self.start_date ).days // 2 )
