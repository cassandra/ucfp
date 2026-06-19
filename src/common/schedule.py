"""A schedule of windowed segments -- a general value object."""
from dataclasses import dataclass
from datetime import date
from typing import Generic, Optional, TypeVar

T = TypeVar( 'T' )


@dataclass( frozen = True )
class Schedule( Generic[ T ] ):
    """An ordered set of windowed segments resolved by date. Each segment must expose a
    `.window` (a `DateWindow`); `at` returns the first segment whose window covers a date,
    or `None` where none does (the caller supplies the meaning of "no segment"). A single
    unbounded segment is a constant schedule -- see `constant`.
    """

    segments : tuple[ T, ... ] = ()

    def at( self, on_date : date ) -> Optional[ T ]:
        """The first segment whose window covers `on_date`, or `None`."""
        for segment in self.segments:
            if segment.window.covers( on_date ):
                return segment
            continue
        return None

    @classmethod
    def constant( cls, segment : T ) -> 'Schedule[ T ]':
        """A one-segment schedule (the segment is expected to have an unbounded window, so
        it is in effect throughout)."""
        return cls( ( segment, ) )
