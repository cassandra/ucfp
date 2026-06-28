"""A calendar date span -- a foundational value object (standard library only).

Lives in `common` so every layer (the Period, the Forecast, and the tax engine's window
protocol) can name it without forming an import cycle.
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

    @property
    def months( self ) -> int:
        """The whole calendar months the span covers, inclusive -- a calendar year is 12, a single
        calendar month is 1. Assumes month-aligned bounds (a first-of-month start and a month-end
        end), as the forecast's period spans are."""
        return ( ( self.end_date.year - self.start_date.year ) * 12
                 + self.end_date.month - self.start_date.month + 1 )
