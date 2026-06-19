"""A date existence window -- a general value object."""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass( frozen = True )
class DateWindow:
    """An inclusive existence window `[start, end]`; `None` on a side means unbounded
    there (so `DateWindow()` covers all dates). Models the WHEN axis of a time-bound input
    -- when an income, expense, asset, or rate set exists -- distinct from a fully-bounded
    `DateSpan` (a concrete interval)."""

    start : Optional[ date ] = None
    end   : Optional[ date ] = None

    def covers( self, on_date : date ) -> bool:
        """Whether `on_date` falls within the window."""
        if ( self.start is not None ) and ( on_date < self.start ):
            return False
        if ( self.end is not None ) and ( on_date > self.end ):
            return False
        return True
