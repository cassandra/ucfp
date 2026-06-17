class AccountsError( Exception ):
    """Base class for accounts-domain errors."""


class AccountStructureError( AccountsError ):
    """Raised when an account violates the chart's structural rules.

    Covers account-type placement (a root must declare a type; a child must
    inherit it, never set one) and parent/child organization consistency.
    """


class SystemAccountError( AccountsError ):
    """Raised when an operation would delete or close a system-managed account."""


class EntryImmutableError( AccountsError ):
    """Raised when an attempt is made to modify an Entry after it is created."""


class TransactionImbalanceError( AccountsError ):
    """Raised when a transaction's entries do not sum to zero in its currency."""


class CurrencyConversionError( AccountsError ):
    """Raised when a requested currency conversion is unavailable."""


class OpeningBalanceError( AccountsError ):
    """Raised when a starting balance cannot be seeded into a journal."""
