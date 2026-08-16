"""Monetary rounding and display helpers for the accounts app."""
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .constants import MONEY_DECIMAL_PLACES


# The smallest representable amount at the money scale (e.g. Decimal('0.00001')),
# used as the quantize() target so the scale lives next to its rounding rule.
_MONEY_QUANTUM = Decimal( 1 ).scaleb( -MONEY_DECIMAL_PLACES )
_CENTS         = Decimal( '0.01' )


def quantize_money( amount : Decimal ) -> Decimal:
    """Round `amount` to the canonical money scale, half-up."""
    return amount.quantize( _MONEY_QUANTUM, rounding = ROUND_HALF_UP )


def round_money_up( amount : Decimal ) -> Decimal:
    """Round `amount` UP to the money scale (toward +infinity). A funding draw uses this so it fully
    covers a cash shortfall -- landing cash at, or a sliver above, the floor rather than the sub-cent
    sliver *below* it that half-up rounding of the draw leaves (the ledger carries full-precision
    Decimals, so a shortfall rarely falls on the money scale exactly)."""
    return amount.quantize( _MONEY_QUANTUM, rounding = ROUND_CEILING )


def format_money( amount : Decimal ) -> str:
    """`amount` as a human-facing dollar string with thousands separators, to the cent
    (`Decimal( '281481.4' )` -> '$281,481.40'). A value that rounds to zero renders as '$0.00', never a
    signed '-$0.00' from a sub-cent negative sliver. For memos and display, not ledger math."""
    if not amount.quantize( _CENTS, rounding = ROUND_HALF_UP ):   # rounds to zero -> drop any negative sign
        amount = Decimal( '0' )
    return f'${amount:,.2f}'
