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

    def compounded( self, exponent : Decimal ) -> 'Rate':
        """This rate over `exponent` of its interval, compounding: `(1 + f) ** exponent - 1`.
        Geometric, so the sub-interval rates multiply back to the full-interval rate -- the
        right translation for a growth rate (e.g. an annual return over a month)."""
        return Rate( ( Decimal( '1' ) + self.fraction ) ** exponent - Decimal( '1' ) )

    def prorated( self, fraction : Decimal ) -> 'Rate':
        """This rate scaled linearly to `fraction` of its interval: `f * fraction`. The
        right translation for a paid-out yield, whose sub-interval amounts sum back to the
        full-interval amount."""
        return Rate( self.fraction * fraction )

    def negated( self ) -> 'Rate':
        """The opposite-sign rate -- e.g. a depreciation (a positive '% lost') expressed as
        the negative growth the projection applies."""
        return Rate( -self.fraction )

    def __str__( self ) -> str:
        """A human-readable percent for memos and logs: rounded to four decimal places, then trailing
        zeros trimmed. `Rate( Decimal( '0.021' ) )` renders as '2.1%'; a long fraction-scaled rate (an
        annual rate prorated to a partial period) rounds rather than printing to full precision."""
        percent = ( self.fraction * 100 ).quantize( Decimal( '0.0001' ) )
        return f'{percent.normalize():f}%'


ZERO_RATE = Rate( Decimal( '0' ) )
# The identity value for a retained-share factor: `.fraction` of 1, so `amount * fraction` is a no-op
# (e.g. the Social Security benefits-payable assumption).
FULL_RATE = Rate( Decimal( '1' ) )
