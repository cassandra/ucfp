"""A proportional rate of change, as a self-documenting value object."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass( frozen = True )
class Rate:
    """A proportional rate of change over one interval, stored as a fraction:
    `Rate( Decimal( '0.03' ) )` is +3%. Storing a fraction (not 3.0 or 1.03) and
    exposing `change_on` / `applied_to` removes the ambiguity of a bare number."""

    fraction : Decimal

    @classmethod
    def percent( cls, value : Decimal ) -> 'Rate':
        """A Rate from a percentage: `Rate.percent( 3 )` is +3%."""
        return cls( Decimal( value ) / Decimal( '100' ) )

    def change_on( self, amount : Decimal ) -> Decimal:
        """The change `amount` undergoes at this rate (the signed delta)."""
        return amount * self.fraction

    def applied_to( self, amount : Decimal ) -> Decimal:
        """`amount` after applying this rate (the grown total)."""
        return amount * ( Decimal( '1' ) + self.fraction )


ZERO_RATE = Rate( Decimal( '0' ) )
