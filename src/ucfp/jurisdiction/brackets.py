"""Country-agnostic tax primitives.

Progressive marginal-rate brackets are common across jurisdictions, so the bracket
table is a shared primitive here; the specific rates and thresholds (the values)
live in a country package's parameters.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass( frozen = True )
class BracketTable:
    """Marginal-rate brackets as `(lower_bound, rate)` rows, ascending by bound.
    `tax_on` returns the cumulative tax on an amount; capital-gains stacking is then
    `tax_on(ordinary + gains) - tax_on(ordinary)`, which spans rate boundaries
    correctly."""

    rows : tuple[ tuple[ Decimal, Decimal ], ... ]

    def tax_on( self, amount : Decimal ) -> Decimal:
        total = Decimal( '0' )
        for index, ( lower, rate ) in enumerate( self.rows ):
            if amount <= lower:
                break
            upper = self.rows[ index + 1 ][ 0 ] if ( index + 1 ) < len( self.rows ) else None
            top = amount if ( upper is None or amount < upper ) else upper
            total += ( top - lower ) * rate
            continue
        return total

    def indexed( self, factor : Decimal ) -> 'BracketTable':
        """This table with every bound scaled by the cumulative COLA `factor` and the rates left
        unchanged -- the inflation-indexing projection (the zero bound stays zero)."""
        return BracketTable( tuple( ( lower * factor, rate ) for lower, rate in self.rows ) )

    def marginal_rate( self, amount : Decimal ) -> Decimal:
        """The marginal rate at `amount` -- the rate of the bracket it falls in, i.e. the rate on the next
        dollar. A bound is the first dollar of its bracket, so an amount sitting exactly on a bound takes
        that bracket's rate. Below the first bound (or with no brackets) the rate is zero."""
        rate = Decimal( '0' )
        for lower, bracket_rate in self.rows:
            if amount < lower:
                break
            rate = bracket_rate
            continue
        return rate

    def ceiling( self, amount : Decimal ) -> Optional[ Decimal ]:
        """The upper bound of the bracket `amount` falls in -- the next bound above it -- or None when it is
        in the top, open-ended bracket. `ceiling - amount` is the headroom left before the next marginal
        rate, the room a tax planner has to realize income at the current rate."""
        for lower, _rate in self.rows:
            if lower > amount:
                return lower
        return None
