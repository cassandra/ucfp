"""Country-agnostic tax primitives.

Progressive marginal-rate brackets are common across jurisdictions, so the bracket
table is a shared primitive here; the specific rates and thresholds (the values)
live in a country package's parameters.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass( frozen = True )
class BracketTable:
    """Marginal-rate brackets as `(lower_bound, rate)` rows, ascending by bound.
    `tax_on` returns the cumulative tax on an amount; capital-gains stacking is then
    `tax_on(ordinary + gains) - tax_on(ordinary)`, which spans rate boundaries
    correctly."""

    rows : tuple

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
