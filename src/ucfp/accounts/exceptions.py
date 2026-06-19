class AccountsError( Exception ):
    """Base class for accounts-domain errors."""


class AccountStructureError( AccountsError ):
    """Raised when an account violates the chart's structural rules.

    Covers account-type placement: a root must declare a type; a child must inherit it,
    never set one; and the tax/asset class fields belong only on their matching type.
    """


class TransactionImbalanceError( AccountsError ):
    """Raised when a transaction's entries do not sum to zero in its currency."""


class CurrencyConversionError( AccountsError ):
    """Raised when a requested currency conversion is unavailable."""


class MissingAccountError( AccountsError ):
    """Raised when a chart operation needs an account the books do not contain."""
