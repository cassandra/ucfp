"""Calendar cadences -- general value objects for placing actual occurrences in time.

A `Cadence` answers one question, `count_in`: how many occurrences fall in a date range. It
places *actual* occurrences -- it does not amortize -- so the count is exact and anchored. Two
kinds:

- `Recurrence` -- repeats every `interval` (every N days/weeks/months/years), the first
  occurrence `offset` past a reference date (default zero). A consumer working at a coarser
  grain (a yearly Period over a monthly recurrence) gets the true per-interval count; a sparse
  recurrence (every 10 years) lands 0 or 1 in a given interval.
- `OneTime` -- a single occurrence on an absolute date; the degenerate, non-repeating cadence.

A consumer asks only `count_in`, so it treats either kind uniformly.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

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

    def months( self ) -> int:
        """This duration as a whole number of months (MONTH or YEAR only). Raises for
        DAY/WEEK, which have no whole-month size."""
        if self.unit == TimeUnit.MONTH:
            return self.count
        if self.unit == TimeUnit.YEAR:
            return self.count * 12
        raise ValueError( f'A {self.unit.label} duration has no whole-month size.' )

    def occurrences_per_year( self ) -> Decimal:
        """How often this recurrence falls in a year, as a `Decimal`: 52 weekly, 12 monthly, 1 yearly,
        a fraction for a multi-unit cadence (every 15 years -> 1/15). Annualizes a per-occurrence amount
        into a yearly rate. Assumes a real recurrence (`count` >= 1)."""
        return _OCCURRENCES_PER_YEAR_BY_UNIT[ self.unit ] / self.count


_OCCURRENCES_PER_YEAR_BY_UNIT = {
    TimeUnit.DAY   : Decimal( 365 ),
    TimeUnit.WEEK  : Decimal( 52 ),
    TimeUnit.MONTH : Decimal( 12 ),
    TimeUnit.YEAR  : Decimal( 1 ),
}

_ZERO_OFFSET = Duration( 0, TimeUnit.DAY )


class Cadence:
    """How occurrences fall in time -- a `Recurrence` (repeats) or a `OneTime` (single dated
    event). Consumers ask only `count_in`, so either kind resolves the same way."""

    def count_in( self, *, start : date, end : date, since : date ) -> int:
        """The number of occurrences in `[start, end]` (inclusive). `since` anchors a relative
        cadence; an absolute one ignores it."""
        raise NotImplementedError


@dataclass( frozen = True )
class Recurrence( Cadence ):
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


@dataclass( frozen = True )
class OneTime( Cadence ):
    """A single occurrence on the absolute date `on` -- the degenerate, non-repeating cadence.
    `since` plays no part: the date is given outright, so the occurrence falls in the one
    interval that contains it, at any granularity."""

    on : date

    def count_in( self, *, start : date, end : date, since : date ) -> int:
        return 1 if start <= self.on <= end else 0
