"""In-memory container types for the accounts app."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from .exceptions import CurrencyConversionError

if TYPE_CHECKING:
    # Referenced only in annotations; importing these at runtime would create a
    # schemas <-> models import cycle.
    from .enums import CurrencyType
    from .models import Account


@dataclass(frozen=True)
class StartingBalance:
    """One account's starting balance, as its natural balance.

    The amount's currency is implicit: it is the account's own currency. This is
    a transient input (e.g. from manual entry or import), not a persisted record.
    """

    account : Account
    amount  : Decimal


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


@dataclass
class OpeningBalances:
    """The transient input that seeds a Baseline's opening state.

    A collection of StartingBalances plus a CurrencyConverter. When every account
    shares the opening transaction's currency the converter is unused (the empty
    default suffices); when currencies differ, it must carry the conversions the
    involved accounts require, or conversion raises.
    """

    starting_balances : list[ StartingBalance ] = field( default_factory = list )
    converter         : CurrencyConverter       = field( default_factory = CurrencyConverter )

    def add( self, account : Account, amount : Decimal ) -> OpeningBalances:
        """Append a StartingBalance for `account`; chainable."""
        self.starting_balances.append( StartingBalance( account = account, amount = amount ) )
        return self
