"""In-memory container types for the accounts app.

Currency conversion is for the GNUCash import boundary: an importer converts foreign source
amounts to the organization's single currency before they enter the books. The in-ledger
model itself is single-currency, so nothing here touches it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from .exceptions import CurrencyConversionError

if TYPE_CHECKING:
    # Referenced only in annotations; imported lazily to avoid a runtime cycle.
    from .enums import CurrencyType


class Handle(Protocol):
    """A stable, unique identity the planning layer mints for an entity an account refers to
    -- its owner (the subject whose account it is) and other planner references. The domain
    treats it opaquely: it needs only a unique ``__str__``, stamps the handle on the account
    (and persists its string), and pairs accounts to subjects by it. The planning layer owns
    the scheme; any object with a unique ``__str__`` qualifies, and a plain ``str`` is the
    simplest one."""

    def __str__(self) -> str:
        ...


@dataclass(frozen=True)
class CurrencyConversion:
    """A grounded conversion: `to_amount = from_amount * conversion_rate`."""

    from_currency_type : CurrencyType
    to_currency_type   : CurrencyType
    conversion_rate    : Decimal

    def __post_init__(self):
        if self.conversion_rate <= 0:
            raise ValueError( 'conversion_rate must be positive.' )
        if ( self.from_currency_type == self.to_currency_type ) and ( self.conversion_rate != 1 ):
            raise ValueError( 'A same-currency conversion must have a rate of 1.' )
        return


class CurrencyConverter:
    """Applies currency conversions, with reverse lookup, raising when it cannot.

    Initialized with zero or more CurrencyConversions. A same-currency request is
    the identity; otherwise a direct (from, to) rate is applied, else the inverse
    of a (to, from) rate, else CurrencyConversionError is raised. Holds no domain
    state, so it is reusable wherever conversion is needed.
    """

    def __init__( self, conversions : 'tuple[CurrencyConversion, ...]' = () ):
        self._rate_by_pair = dict()
        for conversion in conversions:
            pair = ( conversion.from_currency_type, conversion.to_currency_type )
            self._rate_by_pair[ pair ] = conversion.conversion_rate
            continue

    def convert( self,
                 amount             : Decimal,
                 from_currency_type : 'CurrencyType',
                 to_currency_type   : 'CurrencyType' ) -> Decimal:
        if from_currency_type == to_currency_type:
            return amount
        direct_rate = self._rate_by_pair.get( ( from_currency_type, to_currency_type ) )
        if direct_rate is not None:
            return amount * direct_rate
        inverse_rate = self._rate_by_pair.get( ( to_currency_type, from_currency_type ) )
        if inverse_rate is not None:
            return amount / inverse_rate
        raise CurrencyConversionError(
            f'No conversion available from {from_currency_type} to {to_currency_type}.'
        )
