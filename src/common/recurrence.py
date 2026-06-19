"""A calendar recurrence -- a general value object for placing repeating occurrences.

A `Recurrence` is an `interval` (every N days/weeks/months/years) plus an `offset` (how far
past a reference date the first occurrence sits; default zero). It places *actual*
occurrences -- it does not amortize -- so `count_in` is an exact, anchored count of the
occurrences that fall in a date range. A consumer that works at a coarser grain (a yearly
Period over a monthly recurrence) gets the true per-interval count; a sparse recurrence
(every 10 years) lands 0 or 1 in a given interval.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from common.labeled_enum import LabeledEnum


class TimeUnit( LabeledEnum ):
    """The unit a recurrence interval (or offset) is measured in."""

    DAY   = ( 'Day'   , 'Calendar days.' )
    WEEK  = ( 'Week'  , 'Seven-day weeks.' )
    MONTH = ( 'Month' , 'Calendar months (day clamped to month length).' )
    YEAR  = ( 'Year'  , 'Calendar years.' )


def _add_months( anchor : date, months : int ) -> date:
    """`anchor` advanced by `months` calendar months, clamping the day to the target
    month's length (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min( anchor.day, calendar.monthrange( year, month )[ 1 ] )
    return date( year, month, day )


@dataclass( frozen = True )
class Duration:
    """A whole number of `TimeUnit`s. `count` may be zero (e.g. a zero offset)."""

    count : int
    unit  : TimeUnit

    def add_to( self, anchor : date ) -> date:
        """`anchor` advanced by this duration."""
        if self.unit == TimeUnit.DAY:
            return anchor + timedelta( days = self.count )
        if self.unit == TimeUnit.WEEK:
            return anchor + timedelta( weeks = self.count )
        if self.unit == TimeUnit.MONTH:
            return _add_months( anchor, self.count )
        return _add_months( anchor, self.count * 12 )


_ZERO_OFFSET = Duration( 0, TimeUnit.DAY )


@dataclass( frozen = True )
class Recurrence:
    """A repeating occurrence: every `interval`, starting `offset` past a reference date."""

    interval : Duration
    offset   : Duration = _ZERO_OFFSET

    def __post_init__( self ):
        if self.interval.count < 1:
            raise ValueError( 'A recurrence interval must be at least one unit.' )
        return

    def count_in( self, *, start : date, end : date, since : date ) -> int:
        """The number of occurrences in `[start, end]` (inclusive), with the first
        occurrence at `offset` past `since` and each subsequent one an `interval` later."""
        occurrence = self.offset.add_to( since )
        count = 0
        while occurrence <= end:
            if occurrence >= start:
                count += 1
            occurrence = self.interval.add_to( occurrence )
            continue
        return count
