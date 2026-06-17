"""Monetary rounding helpers for the accounts app."""
from decimal import ROUND_HALF_UP, Decimal

from .constants import MONEY_DECIMAL_PLACES


# The smallest representable amount at the money scale (e.g. Decimal('0.00001')),
# used as the quantize() target so the scale lives next to its rounding rule.
_MONEY_QUANTUM = Decimal( 1 ).scaleb( -MONEY_DECIMAL_PLACES )


def quantize_money( amount : Decimal ) -> Decimal:
    """Round `amount` to the canonical money scale, half-up."""
    return amount.quantize( _MONEY_QUANTUM, rounding = ROUND_HALF_UP )
